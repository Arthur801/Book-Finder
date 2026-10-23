"""Shared test worlds: settings, a scripted FakeHost and scripted effects, all rooted in one tmp directory.

Why: the M3a command tests and the M3b state-machine tests must build the same host, so a change to the world
setup is made once. Unit bodies are run through the real entry point (commands.main) with an INVOCATION_ID, the same
path systemd uses, so no test calls the state machine directly.
"""

import io
import json
import shlex
from pathlib import Path

from bookfinder_host import commands as cmd
from bookfinder_host import history as hi
from bookfinder_host import state as st
from bookfinder_host.commands import Deps
from bookfinder_host.config import Settings, make_psql_query
from bookfinder_host.manifest import Migration
from bookfinder_host.testing import FakeClock, FakeEffects, FakeHost, sample_state, write_release

ID1 = "20261010174616_EnablePgvector"
ID2 = "20261010174654_Catalog"
ID3 = "20261010174708_IdentityUserLibrary"
H1 = "a" * 64
H2 = "b" * 64
H3 = "c" * 64
WEB1 = "sha256:" + "1" * 64
WEB2 = "sha256:" + "2" * 64
CRAWLER = "sha256:" + "3" * 64
CRAWLER2 = "sha256:" + "4" * 64
TAG1 = "v1.0.0"
TAG2 = "v1.1.0"
SYSTEMD_UNIT = "book-finder.service"
DIGEST_OK = "sha256:" + "d" * 64
RUN_ID_TEXT = "1234-5"
DEPLOY_RUN_ID = "5555-1"
PUBLIC_URL = "https://book-finder.example"
NOW = "2026-10-23T00:00:00Z"
DEFAULT_STATE = sample_state()


def build_settings(tmp: Path, lock_timeout_s: float = 0.2) -> Settings:
    # /opt and /etc/cron.d exist on the host; the tests create their stand-ins so the installs have a parent.
    (tmp / "opt").mkdir(exist_ok=True)
    (tmp / "cron.d").mkdir(exist_ok=True)
    crawler_conf = tmp / "crawler.conf"
    crawler_conf.write_text(f"CRAWLER_IMAGE=ghcr.io/example/crawler@{WEB1}\nSCHEDULE=0 3 * * *\n", encoding="utf-8")
    return Settings(
        state_file=str(tmp / "state.json"),
        history_file=str(tmp / "history.jsonl"),
        deploy_lock_file=str(tmp / "deploy.lock"),
        web_image_repository="ghcr.io/example/book-finder-web",
        psql_image="docker.io/library/postgres@sha256:" + "f" * 64,
        database_url_parameter="/book-finder/prod/database-url",
        aws_region="ap-northeast-1",
        systemd_unit=SYSTEMD_UNIT,
        compose_project="book-finder",
        lock_timeout_s=lock_timeout_s,
        follow_timeout_s=6000.0,
        public_url=PUBLIC_URL,
        rds_instance_id="book-finder-prod",
        ssm_db_connection="/book-finder/prod/db-connection",
        ssm_openai_key="/book-finder/prod/openai-key",
        ssm_jwt_key="/book-finder/prod/jwt-key",
        crawler_image_repository="ghcr.io/example/book-finder-crawler",
        crawler_conf=str(crawler_conf),
        db_maintenance_lock=str(tmp / "db-maintenance.lock"),
        releases_dir=str(tmp / "releases"),
        run_dir=str(tmp / "run"),
        crawler_runner=str(tmp / "opt" / "run-crawler.sh"),
        cron_file=str(tmp / "cron.d" / "book-finder-crawler"),
    )


class World:
    def __init__(self, tmp_path: Path, state, host: FakeHost, settings: Settings, deps: Deps, fx: FakeEffects) -> None:
        self.tmp_path = tmp_path
        self.state = state
        self.host = host
        self.settings = settings
        self.deps = deps
        self.fx = fx
        self.out = io.StringIO()
        self.err = io.StringIO()

    def run(self, text: str, *, plan_only: bool = False) -> int:
        argv = ["--plan-only"] if plan_only else []
        return cmd.main(argv, {"SSH_ORIGINAL_COMMAND": text}, self.out, self.err, deps=self.deps)

    def run_unit(self, text: str) -> tuple[int, str, str]:
        """Runs the unit body for a deploy text, the way systemd would start it; returns (code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        tokens = shlex.split(text)
        code = cmd.main([cmd.UNIT_BODY_FLAG, *tokens], {"INVOCATION_ID": "test"}, out, err, deps=self.deps)
        return code, out.getvalue(), err.getvalue()

    def stdout_json(self):
        return json.loads(self.out.getvalue())

    def history(self):
        return hi.read(self.settings.history_file)

    def load_state(self) -> st.State:
        return st.load_state(self.settings.state_file)

    def write_state(self, state) -> None:
        Path(self.settings.state_file).write_text(json.dumps(st.state_to_json(state)), encoding="utf-8")

    def remove_state(self) -> None:
        Path(self.settings.state_file).unlink()


def make_world(tmp_path, state=DEFAULT_STATE, *, target=None, release_api="1", db_ids=None, now=NOW, **host_kwargs) -> World:
    settings = build_settings(tmp_path)
    if target is None:
        target = st.applied_migrations(state) if state is not None else []
    target_migrations = [Migration(m.id, m.source_hash) for m in target]
    release_dir = write_release(tmp_path / "release", target_migrations, release_api)
    # The database starts out matching state, not the target: pending migrations are not applied yet.
    recorded = [m.id for m in st.applied_migrations(state)] if state is not None else []
    host_kwargs.setdefault("db_ids", recorded if db_ids is None else db_ids)
    host = FakeHost(release_dir=release_dir, **host_kwargs)
    fx = FakeEffects(host, release_tree=release_dir)
    deps = Deps(
        settings=settings,
        runner=host,
        clock=FakeClock(epoch=1_800_000_000.0, now=now),
        db_query=make_psql_query(host, settings),
        host_api_range=(1, 1),
        effects=fx.as_effects(),
    )
    host.on_systemd_run = cmd.make_inline_launcher(deps)
    world = World(tmp_path, state, host, settings, deps, fx)
    if state is not None:
        world.write_state(state)
    return world


def applied(*pairs):
    return [Migration(i, h) for i, h in pairs]
