"""Scripted fakes for the host program; used by the unit tests and by the TEST-ONLY fakes hook in commands.py.

Why: unit tests must never start docker, systemd or psql, and a scripted runner also records every argv so tests can
assert which commands were (or were not) issued.
"""

import json
import shutil
import stat
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from bookfinder_host.adapters import RealFiles
from bookfinder_host.manifest import Migration
from bookfinder_host.ports import CommandResult, EffectFailed, Effects

Handler = Callable[[Sequence[str]], CommandResult]


class ScriptedRunner:
    def __init__(self, rules: Sequence[tuple[Sequence[str], Handler]]) -> None:
        self._rules = [(tuple(prefix), handler) for prefix, handler in rules]
        self.calls: list[tuple[list[str], Mapping[str, str] | None]] = []

    def calls_argv(self) -> list[list[str]]:
        return [argv for argv, _ in self.calls]

    def run(self, argv: Sequence[str], *, env: Mapping[str, str] | None = None) -> CommandResult:
        self.calls.append((list(argv), env))
        for prefix, handler in self._rules:
            if tuple(argv[: len(prefix)]) == prefix:
                return handler(argv)
        raise AssertionError(f"unexpected command: {list(argv)}")


class FakeClock:
    """Monotonic time that only advances when sleep() is called, so polling loops finish instantly."""

    def __init__(self, start: float = 0.0, epoch: float = 1_800_000_000.0, now: str = "2026-10-23T00:00:00Z") -> None:
        self._time = start
        self._epoch = epoch
        self._now = now

    def monotonic(self) -> float:
        return self._time

    def sleep(self, seconds: float) -> None:
        self._time += seconds

    def epoch(self) -> float:
        return self._epoch

    def now(self) -> str:
        return self._now


def ok(stdout: str = "") -> CommandResult:
    return CommandResult(0, stdout, "")


def sample_state(
    applied: Sequence[Migration] = (),
    revision: int = 1,
    tag: str = "v1.0.0",
    web_digest: str = "sha256:" + "1" * 64,
):
    """A valid docker-runtime state; tests and the demo hook build on it."""
    from bookfinder_host import state as st

    entries = tuple(st.AppliedMigration(m.id, m.source_hash, tag) for m in applied)
    runtime = st.DockerRuntime(
        tag=tag,
        release_api=1,
        web_digest=web_digest,
        crawler_digest="sha256:" + "3" * 64,
        compose_sha256="e" * 64,
        release_dir=f"/opt/book-finder/releases/{tag}",
    )
    schema = st.Schema(
        digest=st.schema_digest(list(applied)),
        applied=entries,
        rebuild=st.Rebuild(tag=tag, web_digest=web_digest),
        dirty=False,
        dirty_since=None,
        dirty_release=None,
    )
    crawler = st.Crawler(
        digest="sha256:" + "3" * 64,
        runner_sha256="5" * 64,
        cron_sha256="6" * 64,
        source_release=st.SourceRelease(tag=tag, web_digest=web_digest),
        paused=None,
    )
    return st.State(revision=revision, runtime=runtime, previous_runtime=None, schema=schema, crawler=crawler)


IMAGE_ID = "sha256:" + "9" * 64
CONTAINER_ID = "0123456789ab"


class FakeHost:
    """Answers the external commands the host issues, from a description of a machine.

    Why: plan and deploy must be exercised end to end without a docker daemon, systemd, or AWS. Unlisted commands fail
    the test loudly instead of quietly succeeding.
    """

    def __init__(
        self,
        *,
        release_dir: Path | None = None,
        db_ids: list[str] | None = None,
        running: bool = True,
        running_image_id: str = IMAGE_ID,
        local_image_id: str = IMAGE_ID,
        unit_states: dict[str, str] | None = None,
        database_url: str = "postgres://fake@db.internal/book_finder",
        containers: list[str] | None = None,
        pull_ok: bool = True,
    ) -> None:
        self.release_dir = release_dir
        self.db_ids = db_ids or []
        self.running = running
        self.running_image_id = running_image_id
        self.local_image_id = local_image_id
        # Maps a transient unit name to its ActiveState; unknown units report LoadState=not-found.
        self.unit_states = unit_states or {}
        self.database_url = database_url
        # Container ids answered for "docker ps"; by default one container when running, none otherwise.
        self.containers = containers if containers is not None else ([CONTAINER_ID] if running else [])
        self.pull_ok = pull_ok
        self.calls: list[list[str]] = []
        # Handles "systemd-run"; commands.make_inline_launcher installs one that runs the unit body in-process.
        self.on_systemd_run: Callable[[Sequence[str]], CommandResult] | None = None
        # Lines that "journalctl -u" returns; informational output only.
        self.journal: list[str] = []

    def run(self, argv: Sequence[str], *, env: Mapping[str, str] | None = None) -> CommandResult:
        command = list(argv)
        self.calls.append(command)
        if command[:2] == ["docker", "create"]:
            return ok(CONTAINER_ID + "\n")
        if command[:2] == ["docker", "rm"]:
            return ok()
        if command[:2] == ["docker", "pull"]:
            return ok() if self.pull_ok else CommandResult(1, "", "manifest unknown")
        if command[:2] == ["docker", "cp"]:
            return self._copy(command[2], Path(command[3]))
        if command[0] == "aws":
            return ok(self.database_url + "\n")
        if command[:2] == ["docker", "run"]:
            return ok("".join(f"{migration_id}\n" for migration_id in self.db_ids))
        if command[:2] == ["docker", "ps"]:
            return ok("".join(f"{container}\n" for container in self.containers))
        if command[:2] == ["docker", "inspect"]:
            return ok(f"{'true' if self.running else 'false'} {self.running_image_id}\n")
        if command[:3] == ["docker", "image", "inspect"]:
            return ok(self.local_image_id + "\n")
        if command[:2] == ["systemctl", "is-active"]:
            return ok(("active" if self.unit_states.get(command[2]) == "active" else "inactive") + "\n")
        if command[:2] == ["systemctl", "show"]:
            unit = command[-1]
            load = "loaded" if unit in self.unit_states else "not-found"
            values = {"LoadState": load, "ActiveState": self.unit_states.get(unit, "inactive")}
            if "--value" in command:
                # systemctl prints only the value of the single requested property.
                requested = [part for part in command if part in values]
                return ok(values[requested[0]] + "\n")
            return ok("".join(f"{name}={value}\n" for name, value in values.items()))
        if command[0] == "systemd-run":
            if self.on_systemd_run is None:
                raise AssertionError("systemd-run reached a FakeHost without an inline launcher")
            return self.on_systemd_run(command)
        if command[0] == "journalctl":
            return ok("".join(f"{line}\n" for line in self.journal))
        raise AssertionError(f"unexpected command: {command}")

    def _copy(self, source: str, dest: Path) -> CommandResult:
        name = source.rsplit("/", 1)[-1]
        if self.release_dir is None or not (self.release_dir / name).is_file():
            return CommandResult(1, "", f"no such file: {name}")
        dest.write_bytes((self.release_dir / name).read_bytes())
        return ok()


FAKE_COMPOSE = "services:\n  web:\n    image: ${WEB_IMAGE}\n"


def write_release(directory: Path, migrations: Sequence[Migration], release_api: str = "1", compose: str = FAKE_COMPOSE) -> Path:
    from bookfinder_host.manifest import render_manifest

    directory.mkdir(parents=True, exist_ok=True)
    (directory / "migrations.txt").write_text(render_manifest(list(migrations)), encoding="utf-8")
    (directory / "RELEASE_API").write_text(release_api + "\n", encoding="utf-8")
    (directory / "compose.prod.yaml").write_text(compose, encoding="utf-8")
    return directory


class FakeEffects:
    """Scripted state-machine effects. Every call is appended to self.trace, so tests can assert the order of steps."""

    def __init__(self, host: FakeHost, *, release_tree: Path | None = None) -> None:
        self.trace: list[str] = []
        self.docker = FakeDocker(self, host, release_tree if release_tree is not None else host.release_dir)
        self.compose = FakeCompose(self)
        # What `docker compose version --short` reports to the host; tests change it to exercise the minimum check.
        self.compose_version = "2.40.0"
        self.aws = FakeAws(self)
        self.ssm = FakeSsm(self)
        self.systemd = FakeSystemd(self)
        self.http = FakeHttp(self)
        self.files = TracingFiles(self)

    def as_effects(self) -> Effects:
        return Effects(
            docker=self.docker,
            compose=self.compose,
            aws=self.aws,
            ssm=self.ssm,
            systemd=self.systemd,
            http=self.http,
            files=self.files,
        )


class FakeDocker:
    def __init__(self, fx: FakeEffects, host: FakeHost, release_tree: Path | None) -> None:
        self.fx = fx
        self.host = host
        self.release_tree = release_tree
        self.pull_error: str | None = None
        self.extract_error: str | None = None
        self.efbundle_rc = 0
        self.efbundle_raises: BaseException | None = None
        # Database ids that the database reports after efbundle runs; None leaves them unchanged.
        self.efbundle_db_ids: list[str] | None = None
        self.efbundle_hook: Callable[[str, str], None] | None = None
        self.smoke_rc = 0
        self.env_files_seen: list[str] = []
        # What the health diagnostics find: the web container ids, and the output docker logs returns for them.
        self.container_ids: list[str] = [CONTAINER_ID]
        self.logs_text = ""
        self.logs_error: str | None = None
        self.logs_calls: list[tuple[str, int]] = []

    def pull(self, reference: str) -> None:
        self.fx.trace.append(f"docker.pull {reference}")
        if self.pull_error is not None:
            raise EffectFailed(self.pull_error)

    def extract_release(self, reference: str, dest: Path) -> None:
        self.fx.trace.append(f"docker.extract {reference}")
        if self.extract_error is not None:
            raise EffectFailed(self.extract_error)
        if self.release_tree is None:
            raise EffectFailed("no release tree configured")
        # copytree with symlinks=True mirrors docker cp without -L: links are copied as links.
        shutil.copytree(self.release_tree, dest, symlinks=True)

    def run_efbundle(self, reference: str, env_file: str) -> int:
        self.fx.trace.append(f"docker.efbundle {reference}")
        self.env_files_seen.append(env_file)
        if self.efbundle_hook is not None:
            self.efbundle_hook(reference, env_file)
        if self.efbundle_raises is not None:
            raise self.efbundle_raises
        if self.efbundle_db_ids is not None:
            self.host.db_ids = list(self.efbundle_db_ids)
        return self.efbundle_rc

    def smoke_crawler(self, reference: str) -> int:
        self.fx.trace.append(f"docker.smoke {reference}")
        return self.smoke_rc

    def web_containers(self, project: str) -> list[str]:
        return list(self.container_ids)

    def logs(self, container: str, tail: int) -> str:
        self.fx.trace.append(f"docker.logs {container}")
        self.logs_calls.append((container, tail))
        if self.logs_error is not None:
            raise EffectFailed(self.logs_error)
        return self.logs_text


class FakeCompose:
    def __init__(self, fx: FakeEffects) -> None:
        self.fx = fx
        self.up_failures = 0
        self.down_failures = 0
        self.up_calls: list[tuple[str, dict[str, str]]] = []
        # How config_json answers the capability probe: literal (a correct Compose), interpolated, error or missing-key.
        self.config_mode = "literal"
        self.config_calls: list[str] = []
        self.probe_dir_mode: int | None = None
        self.down_calls: list[tuple[str, dict[str, str]]] = []
        self.on_up: Callable[[], None] | None = None

    def version(self) -> str:
        # Not traced: the version is read by the plan and the unit before any change, and tests assert on compose calls.
        return self.fx.compose_version + "\n"

    def config_json(self, compose_file: str) -> str:
        # Not traced, like version(): the probe runs before any change and tests assert on the traced compose calls.
        self.config_calls.append(compose_file)
        probe_dir = Path(compose_file).parent
        self.probe_dir_mode = stat.S_IMODE(probe_dir.stat().st_mode)
        if self.config_mode == "error":
            raise EffectFailed("config failed")
        if self.config_mode == "missing-key":
            return json.dumps({"services": {}})
        name, value = (probe_dir / "probe.env").read_text(encoding="utf-8").rstrip("\n").split("=", 1)
        if self.config_mode == "interpolated":
            value = value.replace("$B", "").replace("${HOME}", "/home/probe")
        return json.dumps({"services": {"probe": {"environment": {name: value}}}})

    def up(self, compose_file: str, project: str, env: Mapping[str, str]) -> None:
        self.fx.trace.append(f"compose.up {compose_file}")
        self.up_calls.append((compose_file, dict(env)))
        if self.on_up is not None:
            self.on_up()
        if self.up_failures > 0:
            self.up_failures -= 1
            raise EffectFailed("compose up failed")

    def down(self, compose_file: str, project: str, env: Mapping[str, str]) -> None:
        self.fx.trace.append(f"compose.down {compose_file}")
        self.down_calls.append((compose_file, dict(env)))
        if self.down_failures > 0:
            self.down_failures -= 1
            raise EffectFailed("compose down failed")


class FakeAws:
    def __init__(self, fx: FakeEffects) -> None:
        self.fx = fx
        self.create_error: str | None = None
        self.wait_error: str | None = None
        self.on_create: Callable[[], None] | None = None
        self.created: list[str] = []

    def create_snapshot(self, instance_id: str, snapshot_id: str) -> None:
        self.fx.trace.append(f"aws.create {snapshot_id}")
        if self.on_create is not None:
            self.on_create()
        if self.create_error is not None:
            raise EffectFailed(self.create_error)
        self.created.append(snapshot_id)

    def wait_snapshot_available(self, snapshot_id: str) -> None:
        self.fx.trace.append(f"aws.wait {snapshot_id}")
        if self.wait_error is not None:
            raise EffectFailed(self.wait_error)


class FakeSsm:
    def __init__(self, fx: FakeEffects) -> None:
        self.fx = fx
        self.values: dict[str, str] = {}
        self.missing: set[str] = set()

    def get_parameter(self, name: str) -> str:
        self.fx.trace.append(f"ssm.get {name}")
        if name in self.missing:
            raise EffectFailed(f"parameter {name} not found")
        return self.values.get(name, f"secret-for-{name.strip('/').replace('/', '-')}")


class FakeSystemd:
    def __init__(self, fx: FakeEffects) -> None:
        self.fx = fx
        self.stop_error: str | None = None
        self.start_error: str | None = None

    def stop(self, unit: str) -> None:
        self.fx.trace.append(f"systemd.stop {unit}")
        if self.stop_error is not None:
            raise EffectFailed(self.stop_error)

    def start(self, unit: str) -> None:
        self.fx.trace.append(f"systemd.start {unit}")
        if self.start_error is not None:
            raise EffectFailed(self.start_error)


class FakeHttp:
    def __init__(self, fx: FakeEffects) -> None:
        self.fx = fx
        # Per-URL scripted statuses; the last scripted value repeats. Unscripted URLs answer 200.
        self.script: dict[str, list[int]] = {}
        # When set, decides every status itself; used to tie health results to the phase of the switch.
        self.responder: Callable[[str], int] | None = None
        self.calls: list[tuple[str, dict[str, str]]] = []

    def status(self, url: str, headers: Mapping[str, str], timeout_s: float) -> int:
        self.fx.trace.append(f"http {url}")
        self.calls.append((url, dict(headers)))
        if self.responder is not None:
            return self.responder(url)
        sequence = self.script.get(url)
        if not sequence:
            return 200
        return sequence.pop(0) if len(sequence) > 1 else sequence[0]


class TracingFiles:
    """The real filesystem adapter, with each write recorded; state-machine tests run it against a tmp directory."""

    def __init__(self, fx: FakeEffects) -> None:
        self.fx = fx
        self.real = RealFiles()

    def ensure_dir(self, path: str, mode: int) -> None:
        self.real.ensure_dir(path, mode)

    def read_bytes(self, path: str) -> bytes:
        return self.real.read_bytes(path)

    def write_atomic(self, path: str, data: bytes, mode: int | None) -> None:
        self.fx.trace.append(f"files.write {path}")
        self.real.write_atomic(path, data, mode)

    def remove(self, path: str) -> None:
        self.fx.trace.append(f"files.remove {path}")
        self.real.remove(path)


def write_fakes_file(path: Path, *, settings: dict, host: FakeHost, now: str, epoch: float) -> Path:
    """Serializes the TEST-ONLY fakes description consumed by commands.load_deps (see BOOKFINDER_HOST_TEST_FAKES)."""
    document = {
        "settings": settings,
        "release_dir": str(host.release_dir) if host.release_dir else None,
        "db_ids": host.db_ids,
        "running": host.running,
        "running_image_id": host.running_image_id,
        "local_image_id": host.local_image_id,
        "unit_states": host.unit_states,
        "database_url": host.database_url,
        "now": now,
        "epoch": epoch,
    }
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return path


def fakes_from_file(path: str | Path) -> tuple[dict, FakeHost, FakeClock]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    release_dir = Path(document["release_dir"]) if document.get("release_dir") else None
    host = FakeHost(
        release_dir=release_dir,
        db_ids=document.get("db_ids", []),
        running=document.get("running", True),
        running_image_id=document.get("running_image_id", IMAGE_ID),
        local_image_id=document.get("local_image_id", IMAGE_ID),
        unit_states=document.get("unit_states", {}),
        database_url=document.get("database_url", "postgres://fake@db.internal/book_finder"),
    )
    clock = FakeClock(epoch=document.get("epoch", 1_800_000_000.0), now=document.get("now", "2026-10-23T00:00:00Z"))
    return document, host, clock
