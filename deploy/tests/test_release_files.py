"""Checks the release files shipped in the web image without running docker.

Why: compose.prod.yaml and the Dockerfile must agree on the trusted network and must not carry secrets. These are text
checks, so a drift is caught in the unit suite before an image is built.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
COMPOSE = REPO / "deploy" / "release" / "compose.prod.yaml"
CA_OVERRIDE = REPO / "deploy" / "release" / "compose.ca-bundle.yaml"
DOCKERFILE = REPO / "Dockerfile"
DOCKERIGNORE = REPO / ".dockerignore"


def test_known_networks_equals_web_network_subnet():
    text = COMPOSE.read_text(encoding="utf-8")
    known = re.search(r"ForwardedHeaders__KnownNetworks__0:\s*(\S+)", text).group(1)
    subnet = re.search(r"ipam:\s*\n\s*config:\s*\n\s*-\s*subnet:\s*(\S+)", text).group(1)
    assert known == subnet == "172.31.250.0/24"


def test_compose_publishes_only_loopback_and_holds_no_secrets():
    text = COMPOSE.read_text(encoding="utf-8")
    assert '"127.0.0.1:5000:8080"' in text
    for marker in ("ConnectionStrings", "Jwt__", "OPENAI", "PASSWORD", "password", "Password"):
        assert marker not in text, marker


def test_compose_takes_image_and_env_file_from_the_host():
    text = COMPOSE.read_text(encoding="utf-8")
    assert "${WEB_IMAGE:?" in text
    assert "${WEB_ENV_FILE:?" in text


def test_dockerfile_copies_only_the_two_crawler_host_files():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert (
        "COPY deploy/release/compose.prod.yaml deploy/release/compose.ca-bundle.yaml crawler/deploy/run-crawler.sh crawler/deploy/crawler.cron /out/release/"
    ) in text
    ignore = DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
    assert "crawler/*" in ignore
    assert "!crawler/deploy/run-crawler.sh" in ignore
    assert "!crawler/deploy/crawler.cron" in ignore


def test_ca_override_is_a_read_only_bind_on_web_and_holds_no_path():
    text = CA_OVERRIDE.read_text(encoding="utf-8")
    assert re.search(r"^services:\n  web:\n", text, re.MULTILINE)
    assert "read_only: true" in text
    assert "type: bind" in text
    # The path comes from DB_CA_BUNDLE at run time, so the release never names a host path.
    assert "/etc/book-finder" not in text


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker compose is needed to render the file set")
def test_real_compose_mounts_the_bundle_read_only_on_web(tmp_path):
    bundle = tmp_path / "global-bundle.pem"
    bundle.write_text("-----BEGIN CERTIFICATE-----\nx\n-----END CERTIFICATE-----\n", encoding="utf-8")
    bundle.chmod(0o644)
    web_env = tmp_path / "web.env"
    web_env.write_text("X=1\n", encoding="utf-8")
    base = {
        **{k: v for k, v in os.environ.items() if k != "DB_CA_BUNDLE"},
        "WEB_IMAGE": "example.invalid/web@sha256:" + "1" * 64,
        "WEB_ENV_FILE": str(web_env),
    }

    def render(files, env):
        argv = ["docker", "compose"]
        for name in files:
            argv += ["-f", str(REPO / "deploy" / "release" / name)]
        argv += ["config", "--format", "json"]
        return subprocess.run(argv, env=env, capture_output=True, text=True, check=False)

    rendered = render(["compose.prod.yaml", "compose.ca-bundle.yaml"], {**base, "DB_CA_BUNDLE": str(bundle)})
    assert rendered.returncode == 0, rendered.stderr
    mounts = [v for v in json.loads(rendered.stdout)["services"]["web"]["volumes"] if v["type"] == "bind"]
    assert mounts == [{"type": "bind", "source": str(bundle), "target": str(bundle), "read_only": True}]

    # Without DB_CA_BUNDLE the override refuses to render: a silent default would mount nothing.
    unset = render(["compose.prod.yaml", "compose.ca-bundle.yaml"], base)
    assert unset.returncode != 0 and "DB_CA_BUNDLE" in unset.stderr

    # The release file set without the override does not mount anything, so unset behaviour is unchanged.
    plain = render(["compose.prod.yaml"], base)
    assert plain.returncode == 0, plain.stderr
    assert "bind" not in [v["type"] for v in json.loads(plain.stdout)["services"]["web"].get("volumes", [])]
