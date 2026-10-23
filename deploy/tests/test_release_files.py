"""Checks the release files shipped in the web image without running docker.

Why: compose.prod.yaml and the Dockerfile must agree on the trusted network and must not carry secrets. These are text
checks, so a drift is caught in the unit suite before an image is built.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
COMPOSE = REPO / "deploy" / "release" / "compose.prod.yaml"
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
    assert "COPY deploy/release/compose.prod.yaml crawler/deploy/run-crawler.sh crawler/deploy/crawler.cron /out/release/" in text
    ignore = DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
    assert "crawler/*" in ignore
    assert "!crawler/deploy/run-crawler.sh" in ignore
    assert "!crawler/deploy/crawler.cron" in ignore
