"""Observes the real runtime (docker or systemd) and the real migration history (I1).

Why: the state file is a record of intent. Before any decision the host compares it with what docker, systemd and the
database report, and every mismatch becomes a drift reason instead of being silently trusted.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from bookfinder_host import state as st
from bookfinder_host.images import is_digest_ref
from bookfinder_host.ports import Runner

# Read-only: the history table is EF Core's, and EF writes only ids here.
SCHEMA_QUERY = 'SELECT "MigrationId" FROM "__EFMigrationsHistory";'
_CONTAINER_ID_RE = re.compile(r"[0-9a-f]{12,64}")
_IMAGE_ID_RE = re.compile(r"sha256:[0-9a-f]{64}")
_MIGRATION_ID_RE = re.compile(r"[0-9]{14}_[A-Za-z0-9]+")
_SYSTEMD_ACTIVE_STATES = {"active", "inactive", "activating", "deactivating", "failed", "reloading"}


class ObservationError(Exception):
    """A runtime or database observation could not be made; the caller reports it as drift."""


@dataclass(frozen=True)
class ObservedRuntime:
    kind: str
    running: bool
    image_id: str | None
    containers: int = 1


def observe_docker(runner: Runner, project: str = "book-finder", service: str = "web") -> ObservedRuntime:
    """Finds the web container by compose labels.

    Why: labels identify the service without needing the compose file on the host, and stopped containers are listed
    too (-a) so a leftover container is counted rather than silently ignored.
    """
    listed = runner.run(
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--filter",
            f"label=com.docker.compose.service={service}",
            "--format",
            "{{.ID}}",
        ]
    )
    if listed.returncode != 0:
        raise ObservationError(f"docker ps failed: {listed.stderr.strip()}")
    containers = [line for line in listed.stdout.split("\n") if line]
    for container in containers:
        if _CONTAINER_ID_RE.fullmatch(container) is None:
            raise ObservationError("docker ps returned an unexpected container id")
    if not containers:
        return ObservedRuntime(kind="docker", running=False, image_id=None, containers=0)
    if len(containers) > 1:
        return ObservedRuntime(kind="docker", running=False, image_id=None, containers=len(containers))
    container = containers[0]
    inspected = runner.run(["docker", "inspect", "-f", "{{.State.Running}} {{.Image}}", container])
    if inspected.returncode != 0:
        raise ObservationError(f"docker inspect failed: {inspected.stderr.strip()}")
    parts = inspected.stdout.strip().split(" ")
    if len(parts) != 2 or parts[0] not in ("true", "false") or _IMAGE_ID_RE.fullmatch(parts[1]) is None:
        raise ObservationError(f"unexpected docker inspect output: {inspected.stdout.strip()!r}")
    return ObservedRuntime(kind="docker", running=parts[0] == "true", image_id=parts[1], containers=1)


def image_id_for(runner: Runner, reference: str) -> str:
    if not is_digest_ref(reference):
        raise ObservationError(f"image must be referenced by digest: {reference!r}")
    inspected = runner.run(["docker", "image", "inspect", "-f", "{{.Id}}", reference])
    if inspected.returncode != 0:
        raise ObservationError(f"docker image inspect failed: {inspected.stderr.strip()}")
    image_id = inspected.stdout.strip()
    if _IMAGE_ID_RE.fullmatch(image_id) is None:
        raise ObservationError("docker image inspect returned an unexpected id")
    return image_id


def observe_systemd(runner: Runner, unit: str) -> ObservedRuntime:
    # is-active exits non-zero for inactive units, so the printed state is what matters, not the exit code.
    result = runner.run(["systemctl", "is-active", unit])
    state = result.stdout.strip()
    if state not in _SYSTEMD_ACTIVE_STATES:
        raise ObservationError(f"unexpected systemctl output for {unit}: {state!r}")
    return ObservedRuntime(kind="systemd", running=state == "active", image_id=None)


def check_runtime_matches(
    runtime: st.Runtime,
    observed: ObservedRuntime,
    runner: Runner | None,
    image_repository: str,
) -> list[str]:
    if isinstance(runtime, st.SystemdRuntime):
        if observed.kind != "systemd":
            return [f"runtime kind: state says systemd but observed {observed.kind}"]
        return [] if observed.running else ["runtime: systemd unit is not active"]
    reasons = []
    if observed.kind != "docker":
        reasons.append(f"runtime kind: state says docker but observed {observed.kind}")
        return reasons
    if observed.containers > 1:
        # Two web containers cannot be attributed to one image, so the observation is not usable.
        return ["runtime: multiple web containers"]
    if not observed.running:
        reasons.append("runtime: web container is not running")
    if runner is None:
        raise ValueError("a docker comparison needs a runner to resolve the image id")
    expected_image = image_id_for(runner, f"{image_repository}@{runtime.web_digest}")
    if observed.image_id != expected_image:
        reasons.append(f"runtime: running image {observed.image_id} is not the state image {expected_image}")
    return reasons


def observe_schema(db_query: Callable[[str], str]) -> list[str]:
    """Returns the applied migration ids in ascending order, as the database reports them."""
    lines = [line for line in db_query(SCHEMA_QUERY).split("\n") if line]
    for line in lines:
        if _MIGRATION_ID_RE.fullmatch(line) is None:
            raise ObservationError(f"database returned a malformed migration id: {line!r}")
    if len(set(lines)) != len(lines):
        raise ObservationError("database returned duplicate migration ids")
    # Sorting in Python keeps the order bytewise, independent of the database collation.
    return sorted(lines)


def check_schema_matches(schema: st.Schema, database_ids: list[str]) -> list[str]:
    """The id sequence must equal state's; hashes come from state, which the database cannot prove (N5)."""
    recorded = [entry.id for entry in schema.applied]
    if recorded == database_ids:
        return []
    if len(recorded) != len(database_ids):
        return [f"schema: database has {len(database_ids)} migrations, state records {len(recorded)}"]
    for index, (want, got) in enumerate(zip(recorded, database_ids)):
        if want != got:
            return [f"schema: migration {index} is {got} in the database but {want} in state"]
    return ["schema: id sequence differs from state"]
