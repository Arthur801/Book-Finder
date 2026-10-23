"""Local integration scenarios a-e against real docker (plan M3c, section 3). Opt-in: BOOKFINDER_IT=1 (see deploy/integration).

What is real: the unit body (deploy-entry --unit-body deploy ...) with INVOCATION_ID set, the plan and status entry points,
the admin command, docker, a pgvector container on the docker0 gateway, a registry on 127.0.0.1 that gives the images
real repository@sha256 digests, and images built from this checkout (plus two scratch additive migrations).
What is stubbed: AWS (an executable that answers SSM and RDS) and nginx (deploy/integration/edge_stub.py).
What is not exercised: systemd-run and the systemd runtime; those run only on EC2.

Every docker object is named bf-it-* and removed by the module fixture. Nothing here touches the developer's own
containers, volumes, .env or .vscode.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
HOST = REPO / "deploy" / "host"
ENTRY = HOST / "deploy-entry"
ADMIN = HOST / "book-finder-admin"
EDGE = REPO / "deploy" / "integration" / "edge_stub.py"
sys.path.insert(0, str(HOST))

from bookfinder_host import (
    adapters,
    release_content,
)
from bookfinder_host import manifest as mf
from bookfinder_host import state as st
from bookfinder_host.ports import SubprocessRunner

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("BOOKFINDER_IT") != "1", reason="set BOOKFINDER_IT=1 to run the local integration"),
]

PROJECT = "bf-it-app"
WEB_NAME = "bf-it-web"
CRAWLER_NAME = "bf-it-crawler"
DB_CONTAINER = "bf-it-db"
REGISTRY_CONTAINER = "bf-it-registry"
TAG_V1 = "v1.0.0"
TAG_V2 = "v1.1.0"
TAG_V3 = "v1.2.0"
TAG_BROKEN = "v1.1.1"
# The migrations added to the scratch copies are dated after every real migration, so they always append.
SCRATCH_MIGRATION_2 = "20991231000000_ScratchAdditive"
SCRATCH_MIGRATION_3 = "20991231000001_ScratchSecond"
PSQL_IMAGE_TAG = "pgvector/pgvector:0.8.7-pg17"
DB_USER = "book_finder_dev"
DB_NAME = "book_finder"
GENERIC_WAIT_S = 120


def log(message: str) -> None:
    print(message, flush=True)


def docker(*args: str, check: bool = True, timeout: float = 900) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check, timeout=timeout)


def free_port(host: str = "127.0.0.1") -> int:
    with socket.socket() as probe:
        probe.bind((host, 0))
        return probe.getsockname()[1]


def wait_for(predicate, timeout_s: float, interval_s: float = 0.5) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval_s)
    return False


def tcp_open(host: str, port: int) -> bool:
    # Readiness of the edge itself; an HTTP probe would also wait on the web, which is not up yet.
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def http_status(url: str, headers: dict[str, str] | None = None) -> int:
    request = urllib.request.Request(url, headers=headers or {})

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(request, timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, OSError):
        return 0


@dataclasses.dataclass
class Stack:
    work: Path
    registry: str = ""  # host:port of the throwaway registry
    gateway: str = ""  # docker0 gateway; containers reach the database here
    db_password: str = ""
    db_gateway_port: int = 0
    psql_digest: str = ""  # pgvector image by digest, the psql container used for the schema query
    edge_port: int = 0
    edge: subprocess.Popen | None = None
    digests: dict[str, str] = dataclasses.field(default_factory=dict)  # "v1", "v2", "v3", "broken", "crawler" -> digest
    images: list[str] = dataclasses.field(default_factory=list)
    compose_env: dict[str, str] = dataclasses.field(default_factory=dict)

    @property
    def state_file(self) -> Path:
        return self.work / "state" / "state.json"

    @property
    def history_file(self) -> Path:
        return self.work / "state" / "history.jsonl"

    @property
    def conf(self) -> Path:
        return self.work / "host.conf"

    @property
    def releases(self) -> Path:
        return self.work / "releases"

    @property
    def run_dir(self) -> Path:
        return self.work / "run"

    @property
    def install(self) -> Path:
        return self.work / "install"

    @property
    def aws_stub(self) -> Path:
        return self.work / "bin" / "aws"

    @property
    def aws_log(self) -> Path:
        return self.work / "aws-calls.log"

    @property
    def db_ado(self) -> str:
        return f"Host={self.gateway};Port={self.db_gateway_port};Database={DB_NAME};Username={DB_USER};Password={self.db_password}"

    @property
    def db_url(self) -> str:
        return f"postgres://{DB_USER}:{self.db_password}@{self.gateway}:{self.db_gateway_port}/{DB_NAME}"

    def ref(self, name: str) -> str:
        return f"{self.registry}/{WEB_NAME if name != 'crawler' else CRAWLER_NAME}@{self.digests[name]}"

    def crawler_ref(self) -> str:
        return f"{self.registry}/{CRAWLER_NAME}@{self.digests['crawler']}"


STACK: Stack | None = None


def _write_aws_stub(stack: Stack, ado_password: str) -> None:
    """The SSM stub reads its values from a sibling JSON file, so a scenario can change them between runs."""
    stack.aws_stub.parent.mkdir(parents=True, exist_ok=True)
    parameters = {
        "/bf-it/database-url": stack.db_url,
        "/bf-it/db-connection": stack.db_ado.replace(f"Password={stack.db_password}", f"Password={ado_password}"),
        "/bf-it/openai-key": "sk-bf-it-placeholder-not-a-real-key",
        "/bf-it/jwt-key": "0123456789abcdef" * 4,
    }
    (stack.aws_stub.parent / "aws-config.json").write_text(json.dumps({"parameters": parameters}), encoding="utf-8")
    stub = f"""#!/usr/bin/env python3
# Test double for the AWS CLI: answers SSM from aws-config.json and records RDS snapshot calls. Placeholder values only.
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG = Path({str(stack.aws_log)!r})
argv = sys.argv[1:]
if argv[:2] == ["ssm", "get-parameter"]:
    name = argv[argv.index("--name") + 1]
    parameters = json.loads((HERE / "aws-config.json").read_text(encoding="utf-8"))["parameters"]
    if name not in parameters:
        sys.stderr.write("ParameterNotFound\\n")
        sys.exit(255)
    print(parameters[name])
    sys.exit(0)
if argv[:2] == ["rds", "create-db-snapshot"] or argv[:3] == ["rds", "wait", "db-snapshot-available"]:
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(" ".join(argv) + "\\n")
    sys.exit(0)
sys.stderr.write("unexpected aws call\\n")
sys.exit(9)
"""
    stack.aws_stub.write_text(stub, encoding="utf-8")
    stack.aws_stub.chmod(0o755)


def _write_host_conf(stack: Stack) -> None:
    (stack.work / "state").mkdir(parents=True, exist_ok=True)
    stack.releases.mkdir(parents=True, exist_ok=True)
    stack.run_dir.mkdir(parents=True, exist_ok=True)
    stack.install.mkdir(parents=True, exist_ok=True)
    keys = {
        "STATE_FILE": str(stack.state_file),
        "HISTORY_FILE": str(stack.history_file),
        "DEPLOY_LOCK_FILE": str(stack.work / "state" / "deploy.lock"),
        "DB_MAINTENANCE_LOCK": str(stack.work / "state" / "db-maintenance.lock"),
        "WEB_IMAGE_REPOSITORY": f"{stack.registry}/{WEB_NAME}",
        "CRAWLER_IMAGE_REPOSITORY": f"{stack.registry}/{CRAWLER_NAME}",
        "PSQL_IMAGE": f"pgvector/pgvector@{stack.psql_digest}",
        "DATABASE_URL_PARAMETER": "/bf-it/database-url",
        "AWS_REGION": "ap-northeast-1",
        "AWS_CLI": str(stack.aws_stub),
        "SYSTEMD_UNIT": "book-finder.service",
        "PUBLIC_URL": f"http://127.0.0.1:{stack.edge_port}",
        "RDS_INSTANCE_ID": "bf-it-db",
        "SSM_DB_CONNECTION": "/bf-it/db-connection",
        "SSM_OPENAI_KEY": "/bf-it/openai-key",
        "SSM_JWT_KEY": "/bf-it/jwt-key",
        "COMPOSE_PROJECT": PROJECT,
        "RELEASES_DIR": str(stack.releases),
        "RUN_DIR": str(stack.run_dir),
        "CRAWLER_RUNNER": str(stack.install / "run-crawler.sh"),
        "CRAWLER_CONF": str(stack.install / "crawler.conf"),
        "CRON_FILE": str(stack.install / "crawler.cron"),
        "LOCK_TIMEOUT_S": "5",
        "FOLLOW_TIMEOUT_S": "600",
    }
    stack.conf.write_text("".join(f"{key}={value}\n" for key, value in keys.items()), encoding="utf-8")


def host_env(stack: Stack, **extra: str) -> dict[str, str]:
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": os.environ.get("HOME", "/tmp"),
        "BOOKFINDER_HOST_CONF": str(stack.conf),
    }
    env.update(extra)
    return env


def run_plan(stack: Stack, tag: str, digest: str) -> tuple[int, dict]:
    result = subprocess.run(
        [sys.executable, str(ENTRY), "--plan-only"],
        env=host_env(stack, SSH_ORIGINAL_COMMAND=f"plan {tag} {digest}"),
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    return result.returncode, _last_json(result.stdout)


def run_status(stack: Stack, run_id: str) -> str:
    result = subprocess.run(
        [sys.executable, str(ENTRY)],
        env=host_env(stack, SSH_ORIGINAL_COMMAND=f"status {run_id}"),
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    return _last_json(result.stdout)["status"]


def _last_json(text: str) -> dict:
    lines = [line for line in text.splitlines() if line.startswith("{")]
    return json.loads(lines[-1]) if lines else {}


def unit_tokens(tag: str, web: str, crawler: str, run_id: str, revision: int, runtime: str, schema: str, chain: str) -> list[str]:
    return [
        "deploy",
        tag,
        web,
        crawler,
        "--run-id",
        run_id,
        "--expect-revision",
        str(revision),
        "--expect-runtime",
        runtime,
        "--expect-schema",
        schema,
        "--chain",
        chain,
    ]


def start_unit(stack: Stack, tokens: list[str], name: str) -> subprocess.Popen:
    # The unit body is started with the same arguments the SSH side would hand to systemd-run; INVOCATION_ID marks it.
    stdout = (stack.work / f"{name}.out").open("w", encoding="utf-8")
    stderr = (stack.work / f"{name}.err").open("w", encoding="utf-8")
    return subprocess.Popen(
        [sys.executable, str(ENTRY), "--unit-body", *tokens],
        env=host_env(stack, INVOCATION_ID=f"bf-it-{name}"),
        stdout=stdout,
        stderr=stderr,
    )


def run_unit(stack: Stack, tokens: list[str], name: str) -> tuple[int, str, str]:
    process = start_unit(stack, tokens, name)
    code = process.wait(timeout=1800)
    return code, (stack.work / f"{name}.out").read_text(encoding="utf-8"), (stack.work / f"{name}.err").read_text(encoding="utf-8")


def run_admin(stack: Stack, argv: list[str], typed: str) -> tuple[int, str, str]:
    result = subprocess.run(
        [sys.executable, str(ADMIN), *argv],
        env=host_env(stack, SUDO_USER="bf-it-operator"),
        input=typed + "\n",
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    return result.returncode, result.stdout, result.stderr


def read_state() -> dict:
    return json.loads(Path(STACK.state_file).read_text(encoding="utf-8"))


def read_history() -> list[dict]:
    return [json.loads(line) for line in STACK.history_file.read_text(encoding="utf-8").splitlines() if line]


def completed_for(run_id: str) -> dict:
    return [entry for entry in read_history() if entry.get("run_id") == run_id and entry.get("phase") == "completed"][-1]


def web_container_image_ids() -> list[str]:
    listed = docker("ps", "-q", "--filter", f"label=com.docker.compose.project={PROJECT}", "--filter", "label=com.docker.compose.service=web").stdout.split()
    return [docker("inspect", "-f", "{{.Image}}", container).stdout.strip() for container in listed]


def local_image_id(reference: str) -> str:
    return docker("image", "inspect", "-f", "{{.Id}}", reference).stdout.strip()


def manifest_of(directory: Path) -> list[mf.Migration]:
    return mf.read_manifest_file(directory / "migrations.txt")


def scratch_tree(destination: Path, extra: list[tuple[str, str]]) -> None:
    """Copies the tracked and untracked (not ignored) files of this checkout and adds scratch migrations.

    Why: the copy is never committed, so the real tree is unchanged; git ls-files keeps out build output and .venv.
    """
    listed = subprocess.run(["git", "-C", str(REPO), "ls-files", "-co", "--exclude-standard", "-z"], capture_output=True, check=True).stdout.split(b"\0")
    for raw in filter(None, listed):
        relative = raw.decode("utf-8")
        if relative.startswith((".venv", ".vscode")):
            continue
        source = REPO / relative
        if not source.is_file():
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    migrations = destination / "Infrastructure" / "Persistence" / "Migrations"
    for identifier, body in extra:
        (migrations / f"{identifier}.cs").write_text(_scratch_cs(identifier, body), encoding="utf-8")
        (migrations / f"{identifier}.Designer.cs").write_text(_scratch_designer(identifier), encoding="utf-8")


def _scratch_cs(identifier: str, column: str) -> str:
    return f"""using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Book_Finder.Infrastructure.Persistence.Migrations
{{
    /// <summary>Scratch additive migration for the local integration run only; never committed.</summary>
    public partial class {identifier.split("_", 1)[1]} : Migration
    {{
        protected override void Up(MigrationBuilder migrationBuilder)
        {{
            migrationBuilder.AddColumn<string>(name: "{column}", table: "books", type: "text", nullable: true);
        }}

        protected override void Down(MigrationBuilder migrationBuilder)
        {{
            migrationBuilder.DropColumn(name: "{column}", table: "books");
        }}
    }}
}}
"""


def _scratch_designer(identifier: str) -> str:
    return f"""// <auto-generated />
using Book_Finder.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Book_Finder.Infrastructure.Persistence.Migrations
{{
    [DbContext(typeof(AppDbContext))]
    [Migration("{identifier}")]
    partial class {identifier.split("_", 1)[1]}
    {{
    }}
}}
"""


def build_image(tag: str, context: Path, log_file: Path, dockerfile: str | None = None) -> None:
    command = ["docker", "build", "-t", tag]
    if dockerfile is not None:
        command += ["-f", "-"]
    command.append(str(context))
    with log_file.open("w", encoding="utf-8") as handle:
        result = subprocess.run(command, input=dockerfile, stdout=handle, stderr=subprocess.STDOUT, text=True, check=False, timeout=3600)
    assert result.returncode == 0, f"docker build {tag} failed; see {log_file}"


def push(stack: Stack, local_tag: str, repository: str) -> str:
    remote = f"{stack.registry}/{repository}:{local_tag.rsplit(':', 1)[1]}"
    docker("tag", local_tag, remote)
    pushed = docker("push", remote).stdout
    match = re.search(r"digest: (sha256:[0-9a-f]{64})", pushed)
    assert match, pushed
    stack.images.append(remote)
    return match.group(1)


def seed_connection_env(stack: Stack, path: Path, ado: str) -> Path:
    path.write_text(f"ConnectionStrings__DefaultConnection={ado}\n", encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    global STACK
    work = tmp_path_factory.mktemp("bf-it")
    stack = Stack(work=work)
    STACK = stack
    started: list[str] = []
    try:
        # Database and registry first: the images are pushed to the registry and the schema is applied in the database.
        stack.db_password = os.urandom(12).hex()
        stack.gateway = docker("network", "inspect", "bridge", "-f", "{{(index .IPAM.Config 0).Gateway}}").stdout.strip()
        stack.db_gateway_port = free_port(stack.gateway)
        local_db_port = free_port()
        docker(
            "run",
            "-d",
            "--name",
            DB_CONTAINER,
            "-e",
            f"POSTGRES_DB={DB_NAME}",
            "-e",
            f"POSTGRES_USER={DB_USER}",
            "-e",
            f"POSTGRES_PASSWORD={stack.db_password}",
            "-p",
            f"127.0.0.1:{local_db_port}:5432",
            "-p",
            f"{stack.gateway}:{stack.db_gateway_port}:5432",
            PSQL_IMAGE_TAG,
        )
        started.append(DB_CONTAINER)
        assert wait_for(
            lambda: docker("exec", DB_CONTAINER, "pg_isready", "-h", "127.0.0.1", "-U", DB_USER, "-d", DB_NAME, check=False).returncode == 0,
            120,
        ), "database did not accept connections"
        stack.psql_digest = docker("image", "inspect", "-f", "{{index .RepoDigests 0}}", PSQL_IMAGE_TAG).stdout.strip().split("@", 1)[1]

        docker("run", "-d", "--name", REGISTRY_CONTAINER, "-p", "127.0.0.1::5000", "registry:2")
        started.append(REGISTRY_CONTAINER)
        registry_port = docker("port", REGISTRY_CONTAINER, "5000/tcp").stdout.strip().rsplit(":", 1)[1]
        stack.registry = f"127.0.0.1:{registry_port}"
        assert wait_for(lambda: http_status(f"http://{stack.registry}/v2/") == 200, 60), "registry did not answer"

        # Images: the current tree, two scratch copies (each adds migrations), a derived broken image and the crawler.
        logs = stack.work / "logs"
        logs.mkdir()
        build_image(f"{WEB_NAME}:v1", REPO, logs / "web-v1.log")
        stack.images.append(f"{WEB_NAME}:v1")
        v2_src = stack.work / "src-v2"
        scratch_tree(v2_src, [(SCRATCH_MIGRATION_2, "scratch_note")])
        build_image(f"{WEB_NAME}:v2", v2_src, logs / "web-v2.log")
        stack.images.append(f"{WEB_NAME}:v2")
        v3_src = stack.work / "src-v3"
        scratch_tree(v3_src, [(SCRATCH_MIGRATION_2, "scratch_note"), (SCRATCH_MIGRATION_3, "scratch_note_two")])
        build_image(f"{WEB_NAME}:v3", v3_src, logs / "web-v3.log")
        stack.images.append(f"{WEB_NAME}:v3")
        empty_context = stack.work / "empty-context"
        empty_context.mkdir()
        build_image(f"{WEB_NAME}:broken", empty_context, logs / "web-broken.log", dockerfile=f'FROM {WEB_NAME}:v2\nENTRYPOINT ["sh", "-c", "exit 1"]\n')
        stack.images.append(f"{WEB_NAME}:broken")
        build_image(f"{CRAWLER_NAME}:local", REPO / "crawler", logs / "crawler.log")
        stack.images.append(f"{CRAWLER_NAME}:local")

        for name, tag in (("v1", "v1"), ("v2", "v2"), ("v3", "v3"), ("broken", "broken")):
            stack.digests[name] = push(stack, f"{WEB_NAME}:{tag}", WEB_NAME)
        stack.digests["crawler"] = push(stack, f"{CRAWLER_NAME}:local", CRAWLER_NAME)

        stack.edge_port = free_port()
        stack.edge = subprocess.Popen([sys.executable, str(EDGE), str(stack.edge_port), "5000"])
        assert wait_for(lambda: tcp_open("127.0.0.1", stack.edge_port), 30), "edge stub did not start"

        _write_aws_stub(stack, ado_password=stack.db_password)
        _write_host_conf(stack)
        yield stack
    finally:
        if stack.edge is not None:
            stack.edge.terminate()
            stack.edge.wait(timeout=10)
        _remove_project_objects()
        for container in started:
            docker("rm", "-fv", container, check=False)
        for image in stack.images:
            docker("rmi", "-f", image, check=False)
        STACK = None
        log("cleanup: removed bf-it containers, images, the registry and the database")


def _remove_project_objects() -> None:
    # Compose-labelled containers, networks and volumes of the bf-it-app project; the compose file is not needed for this.
    label = f"label=com.docker.compose.project={PROJECT}"
    containers = docker("ps", "-aq", "--filter", label, check=False).stdout.split()
    if containers:
        docker("rm", "-fv", *containers, check=False)
    for network in docker("network", "ls", "-q", "--filter", label, check=False).stdout.split():
        docker("network", "rm", network, check=False)
    for volume in docker("volume", "ls", "-q", "--filter", label, check=False).stdout.split():
        docker("volume", "rm", volume, check=False)


def _release_extract(stack: Stack, name: str, digest: str) -> Path:
    destination = stack.releases / digest.split(":", 1)[1]
    if not destination.exists():
        reference = f"{stack.registry}/{WEB_NAME}@{digest}"
        docker("pull", reference)
        adapters.RealDocker(SubprocessRunner()).extract_release(reference, destination)
    return destination


def _compose_up(stack: Stack, compose_file: Path, web_ref: str, env_file: Path) -> None:
    subprocess.run(
        ["docker", "compose", "-p", PROJECT, "-f", str(compose_file), "up", "-d", "--remove-orphans"],
        env={**os.environ, "WEB_IMAGE": web_ref, "WEB_ENV_FILE": str(env_file)},
        capture_output=True,
        text=True,
        check=True,
        timeout=600,
    )


def _wait_local(stack: Stack, timeout_s: float = 120) -> bool:
    return wait_for(lambda: http_status("http://127.0.0.1:5000/", {"X-Forwarded-Proto": "https"}) == 200, timeout_s, 2)


def _current(stack: Stack) -> dict:
    state = read_state()
    return {"revision": state["revision"], "runtime": state["runtime"]["web_digest"], "schema": state["schema"]["digest"]}


def _web_digest_of_container(stack: Stack) -> str:
    image_ids = web_container_image_ids()
    assert len(image_ids) == 1, f"expected one web container, found {len(image_ids)}"
    return image_ids[0]


def test_a_forward_upgrade_with_snapshot_and_crawler_pause(stack: Stack):
    # Starting state written by a test helper: database at the v1 manifest, v1 running through compose (bootstrap itself
    # needs systemd and is covered by the unit tests).
    seed = seed_connection_env(stack, stack.work / "seed.env", stack.db_ado)
    v1_ref = f"{stack.registry}/{WEB_NAME}@{stack.digests['v1']}"
    docker("run", "--rm", "--pull=never", "--env-file", str(seed), "--entrypoint", "/app/efbundle", v1_ref)
    v1_dir = _release_extract(stack, "v1", stack.digests["v1"])
    v1_manifest = manifest_of(v1_dir)
    run_env = stack.run_dir / "web-seed.env"
    run_env.write_text(
        f"ConnectionStrings__DefaultConnection={stack.db_ado}\nOPENAIAPI_KEY=sk-bf-it-placeholder-not-a-real-key\nJwt__SigningKey={'0123456789abcdef' * 4}\n",
        encoding="utf-8",
    )
    _compose_up(stack, v1_dir / release_content.COMPOSE_FILE, v1_ref, run_env)
    assert _wait_local(stack), "v1 did not answer"
    compose_sha = release_content.compose_sha256_of(v1_dir)
    crawler_digest = stack.digests["crawler"]
    (stack.install / "crawler.conf").write_text(f"CRAWLER_IMAGE={stack.registry}/{CRAWLER_NAME}@{crawler_digest}\n", encoding="utf-8")
    state = st.State(
        revision=0,
        runtime=st.DockerRuntime(
            tag=TAG_V1,
            release_api=1,
            web_digest=stack.digests["v1"],
            crawler_digest=crawler_digest,
            compose_sha256=compose_sha,
            release_dir=str(v1_dir),
        ),
        previous_runtime=None,
        schema=st.Schema(
            digest=st.schema_digest(v1_manifest),
            applied=tuple(st.AppliedMigration(m.id, m.source_hash, TAG_V1) for m in v1_manifest),
            rebuild=st.Rebuild(tag=TAG_V1, web_digest=stack.digests["v1"]),
            dirty=False,
            dirty_since=None,
            dirty_release=None,
        ),
        crawler=st.Crawler(digest=crawler_digest, paused=None),
    )
    st.write_state(stack.state_file, state, expected_revision=0)

    code, plan = run_plan(stack, TAG_V2, stack.digests["v2"])
    assert code == 0 and plan["classification"] == "forward", plan
    assert len(plan["pending"]) == 1

    current = _current(stack)
    code, out, err = run_unit(
        stack,
        unit_tokens(TAG_V2, stack.digests["v2"], crawler_digest, "9001-1", current["revision"], current["runtime"], current["schema"], "forward"),
        "a",
    )
    assert code == 0, f"exit {code}\n{out}\n{err}"
    calls = stack.aws_log.read_text(encoding="utf-8")
    assert "create-db-snapshot" in calls and "wait db-snapshot-available" in calls
    state_after = read_state()
    assert state_after["runtime"]["tag"] == TAG_V2 and state_after["runtime"]["web_digest"] == stack.digests["v2"]
    assert state_after["schema"]["rebuild"] == {"tag": TAG_V2, "web_digest": stack.digests["v2"]}
    assert state_after["schema"]["dirty"] is False and state_after["crawler"]["paused"] is None
    assert len(state_after["schema"]["applied"]) == len(v1_manifest) + 1
    record = completed_for("9001-1")
    assert record["result"] == "success" and record.get("snapshot_id")
    assert _web_digest_of_container(stack) == local_image_id(f"{stack.registry}/{WEB_NAME}@{stack.digests['v2']}")
    log("PASS a: forward upgrade to v2 with snapshot, crawler paused then resumed, web on v2 digest")


def test_b_schema_ahead_deploy_keeps_rebuild_target(stack: Stack):
    before = read_state()
    current = _current(stack)
    code, out, err = run_unit(
        stack,
        unit_tokens(TAG_V1, stack.digests["v1"], stack.digests["crawler"], "9002-1", current["revision"], current["runtime"], current["schema"], "schema-ahead"),
        "b",
    )
    assert code == 0, f"exit {code}\n{out}\n{err}"
    after = read_state()
    assert after["runtime"]["tag"] == TAG_V1 and after["previous_runtime"]["tag"] == TAG_V2
    assert after["schema"]["rebuild"] == before["schema"]["rebuild"] == {"tag": TAG_V2, "web_digest": stack.digests["v2"]}
    assert after["schema"]["applied"] == before["schema"]["applied"]
    assert _web_digest_of_container(stack) == local_image_id(f"{stack.registry}/{WEB_NAME}@{stack.digests['v1']}")
    log("PASS b: schema-ahead deploy to v1 succeeded, schema rebuild stayed at v2")


def test_c_broken_web_image_rolls_back(stack: Stack):
    current = _current(stack)
    code, out, err = run_unit(
        stack,
        unit_tokens(TAG_BROKEN, stack.digests["broken"], stack.digests["crawler"], "9003-1", current["revision"], current["runtime"], current["schema"], "in-sync"),
        "c",
    )
    assert code == 1, f"exit {code}\n{out}\n{err}"
    assert completed_for("9003-1")["result"] == "rolled-back"
    state_after = read_state()
    assert state_after["runtime"]["web_digest"] == stack.digests["v1"]
    assert _web_digest_of_container(stack) == local_image_id(f"{stack.registry}/{WEB_NAME}@{stack.digests['v1']}")
    log("PASS c: broken image failed its health check and the previous release (v1) was restored, exit 1")


def test_d_failed_migration_keeps_dirty_and_paused_until_reconciled(stack: Stack):
    # A wrong password for the migration connection makes efbundle fail before anything is applied.
    _write_aws_stub(stack, ado_password="wrong-" + stack.db_password)
    current = _current(stack)
    code, out, err = run_unit(
        stack,
        unit_tokens(TAG_V3, stack.digests["v3"], stack.digests["crawler"], "9004-1", current["revision"], current["runtime"], current["schema"], "forward"),
        "d1",
    )
    assert code == 4, f"exit {code}\n{out}\n{err}"
    state_failed = read_state()
    assert state_failed["schema"]["dirty"] is True and state_failed["crawler"]["paused"] is not None
    assert completed_for("9004-1")["result"] == "failed-migration"

    _write_aws_stub(stack, ado_password=stack.db_password)
    current = _current(stack)
    code, out, err = run_unit(
        stack,
        unit_tokens(TAG_V3, stack.digests["v3"], stack.digests["crawler"], "9005-1", current["revision"], current["runtime"], current["schema"], "forward"),
        "d2",
    )
    assert code == 6, f"exit {code}\n{out}\n{err}"

    # The database still holds the v2 manifest, so the prefix digest is the recorded schema digest.
    expected = read_state()["schema"]["digest"]
    code, _, err = run_admin(
        stack,
        [
            "reconcile-schema",
            "--mark-clean",
            "--rebuild-release",
            TAG_V2,
            "--rebuild-web-digest",
            stack.digests["v2"],
            "--expect-schema-digest",
            expected,
            "--reason",
            "integration: verified database ids",
            "--yes-i-verified",
            expected,
        ],
        typed=expected,
    )
    assert code == 0, err
    assert read_state()["schema"]["dirty"] is False
    code, _, err = run_admin(
        stack,
        ["resume-crawler", "--crawler-digest", stack.digests["crawler"], "--reason", "integration: verified crawler"],
        typed=stack.digests["crawler"],
    )
    assert code == 0, err
    assert read_state()["crawler"]["paused"] is None
    log("PASS d: failed migration left dirty and paused (exit 4), next deploy refused (exit 6), reconcile-schema and resume-crawler cleared both")


def test_e_killed_run_is_indeterminate_until_the_operator_resolves_it(stack: Stack):
    current = _current(stack)
    process = start_unit(
        stack,
        unit_tokens(TAG_V3, stack.digests["v3"], stack.digests["crawler"], "9006-1", current["revision"], current["runtime"], current["schema"], "forward"),
        "e",
    )
    # Kill the unit body as soon as the dirty flag is on disk; the migration container may still finish on its own.
    assert wait_for(lambda: read_state()["schema"]["dirty"] is True, 120, 0.05), "dirty flag never appeared"
    os.kill(process.pid, signal.SIGKILL)
    process.wait(timeout=30)
    assert wait_for(
        lambda: not docker("ps", "-q", "--filter", "ancestor=" + f"{stack.registry}/{WEB_NAME}@{stack.digests['v3']}", check=False).stdout.strip(), 180, 2
    ), "migration container did not finish"

    assert run_status(stack, "9006-1") == "indeterminate"
    code, plan = run_plan(stack, TAG_V3, stack.digests["v3"])
    assert code == 8, plan
    code, _, err = run_admin(stack, ["resolve-run", "9006-1", "--result", "failed-migration", "--reason", "integration: killed during migration"], typed="9006-1")
    assert code == 0, err
    assert run_status(stack, "9006-1") == "completed:failed-migration"
    code, plan = run_plan(stack, TAG_V3, stack.digests["v3"])
    assert code == 6, plan  # the schema is still dirty; resolve-run does not touch state (N7)
    log("PASS e: killed run reported indeterminate (plan exit 8), resolve-run recorded the outcome, dirty stays until reconciled")
