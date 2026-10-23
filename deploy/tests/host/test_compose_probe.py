"""The raw env_file capability probe: what counts as supported, and that its temp directory never outlives the call.

Why: the host refuses a Compose that would interpolate secrets. Each outcome (correct, interpolated, error, missing key,
bad JSON) is checked here with a stub, and the directory cleanup is checked on every path.
"""

import json
import stat
from pathlib import Path

import pytest
from bookfinder_host import machine
from bookfinder_host.ports import EffectFailed


class StubCompose:
    def __init__(self, *, mode="literal", version="2.40.0\n", version_error=False) -> None:
        self.mode = mode
        self._version = version
        self.version_error = version_error
        self.seen_dirs: list[Path] = []
        self.seen_modes: list[int] = []
        self.seen_compose_text: list[str] = []

    def version(self) -> str:
        if self.version_error:
            raise EffectFailed("docker compose version failed")
        return self._version

    def config_json(self, compose_file: str) -> str:
        probe_dir = Path(compose_file).parent
        self.seen_dirs.append(probe_dir)
        self.seen_modes.append(stat.S_IMODE(probe_dir.stat().st_mode))
        self.seen_compose_text.append(Path(compose_file).read_text(encoding="utf-8"))
        if self.mode == "error":
            raise EffectFailed("config failed")
        if self.mode == "not-json":
            return "services: {"
        if self.mode == "missing-key":
            return json.dumps({"services": {"probe": {"environment": {}}}})
        name, value = (probe_dir / "probe.env").read_text(encoding="utf-8").rstrip("\n").split("=", 1)
        if self.mode == "interpolated":
            value = value.replace("$B", "").replace("${HOME}", "/home/probe")
        if self.mode == "escaped":
            # The form Compose 5.6.0 actually prints: every literal $ doubled.
            value = value.replace("$", "$$")
        return json.dumps({"services": {"probe": {"environment": {name: value}}}})


def test_literal_value_is_supported(tmp_path):
    compose = StubCompose()
    assert machine.compose_supports_raw_env_file(compose, tmp_path) is True
    assert list(tmp_path.iterdir()) == []


def test_the_probe_directory_is_private_and_has_the_expected_files(tmp_path):
    compose = StubCompose()
    machine.compose_supports_raw_env_file(compose, tmp_path)
    assert compose.seen_modes == [0o700]
    assert "env_file:" in compose.seen_compose_text[0] and "format: raw" in compose.seen_compose_text[0]


def test_escaped_literal_as_printed_by_compose_is_supported(tmp_path):
    assert machine.compose_supports_raw_env_file(StubCompose(mode="escaped"), tmp_path) is True
    assert list(tmp_path.iterdir()) == []


def test_default_format_interpolation_is_refused(tmp_path):
    class Default(StubCompose):
        def config_json(self, compose_file):
            probe_dir = Path(compose_file).parent
            self.seen_dirs.append(probe_dir)
            # Default env_file parsing: $B blanked, ${HOME} expanded, quotes dropped.
            return json.dumps({"services": {"probe": {"environment": {"PROBE": "a/home/probe'\"#x"}}}})

    assert machine.compose_supports_raw_env_file(Default(), tmp_path) is False


def test_interpolated_value_is_refused(tmp_path):
    compose = StubCompose(mode="interpolated")
    assert machine.compose_supports_raw_env_file(compose, tmp_path) is False
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("mode", ["error", "missing-key", "not-json"])
def test_compose_failures_are_refused(tmp_path, mode):
    compose = StubCompose(mode=mode)
    assert machine.compose_supports_raw_env_file(compose, tmp_path) is False
    assert list(tmp_path.iterdir()) == []


def test_refusal_message_carries_the_version_it_found(tmp_path):
    version, problem = machine.compose_raw_env_check(StubCompose(mode="interpolated", version="2.27.1\n"), tmp_path)
    assert version == "2.27.1"
    assert problem == "docker compose does not support env_file format: raw (found 2.27.1)"
    assert list(tmp_path.iterdir()) == []


def test_unreadable_version_is_reported_and_the_probe_still_decides(tmp_path):
    version, problem = machine.compose_raw_env_check(StubCompose(version_error=True), tmp_path)
    assert version.startswith("unknown (")
    assert problem is None


def test_directory_is_removed_even_when_the_probe_raises(tmp_path):
    class Boom(StubCompose):
        def config_json(self, compose_file):
            super().config_json(compose_file)
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        machine.compose_supports_raw_env_file(Boom(), tmp_path)
    assert list(tmp_path.iterdir()) == []
