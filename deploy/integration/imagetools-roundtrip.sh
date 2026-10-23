#!/usr/bin/env bash
# Round-trip check for the CD release-tag step (#92): `docker buildx imagetools create` must keep the attested digest.
#
# What is real: a throwaway registry:2 container, a single-platform image built and pushed the way cd.yml does it
# (docker build, docker push, digest from RepoDigests), buildx imagetools, and the digest resolution in
# .github/scripts/cd_release.py (image_state and confirm_release_digest), called directly from this script.
# The only thing changed is the registry name guard: cd_release.py admits only the ghcr.io CD repositories, so the
# script widens that regex to the local registry prefix and nothing else.
#
# Local http registry: no buildx builder and no daemon.json change are needed. The Docker daemon treats 127.0.0.0/8 as
# an insecure registry by default (docker info -> RegistryConfig.InsecureRegistryCIDRs), so the push and the buildx
# imagetools calls reach http://127.0.0.1:<port> with the default docker driver. Verified on Docker 29.9.1 and buildx v0.38.0.
#
# Every object is named bf-ci-roundtrip-* or lives in the throwaway registry, which is removed by the trap, together with
# the local image tag. Base images are pulled by digest and kept as a cache.
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd_release="$repo_root/.github/scripts/cd_release.py"
REGISTRY_IMAGE="registry:2.8.3@sha256:a3d8aaa63ed8681a604f1dea0aa03f100d5895b6a58ace528858a7b332415373"
# The runtime-deps base from the root Dockerfile, pinned by digest.
BASE_IMAGE="mcr.microsoft.com/dotnet/runtime-deps:10.0.13-noble@sha256:1c20bc9ebda297198be069d82b6c5d1716faeeec8b8dca53ef963f9c92d3e2e3"
RELEASE_TAG="v0.0.0"
CONTROL_TAG="v0.0.1"

run_id="$$-$(date +%s)"
registry_container="bf-ci-roundtrip-registry-$run_id"
build_dir=""
local_images=()

cleanup() {
  local status=$?
  set +e
  docker rm -f "$registry_container" >/dev/null 2>&1
  for image in "${local_images[@]}"; do
    docker rmi -f "$image" >/dev/null 2>&1
  done
  if [[ -n $build_dir ]]; then
    rm -rf "$build_dir"
  fi
  exit "$status"
}
trap cleanup EXIT

fail() {
  echo "FAIL roundtrip: $*" >&2
  exit 1
}

# Port 0 on 127.0.0.1 lets docker pick a free ephemeral port, so the test never races another process for a fixed one.
docker run -d --name "$registry_container" -p 127.0.0.1::5000 "$REGISTRY_IMAGE" >/dev/null
port=$(docker port "$registry_container" 5000/tcp | head -n 1 | awk -F: '{print $NF}')
[[ $port =~ ^[0-9]+$ ]] || fail "could not read the registry port"
for _ in $(seq 1 120); do
  curl -fsS "http://127.0.0.1:$port/v2/" >/dev/null 2>&1 && break
  sleep 0.5
done
curl -fsS "http://127.0.0.1:$port/v2/" >/dev/null || fail "registry did not answer on 127.0.0.1:$port"

prefix="127.0.0.1:$port/bf-ci/roundtrip"
staging="$prefix:staging"
release_ref="$prefix:$RELEASE_TAG"
control_ref="$prefix:$CONTROL_TAG"

# Same build and digest method as cd.yml: docker build, docker push, then the first RepoDigest of the pushed image.
build_dir=$(mktemp -d)
printf 'FROM %s\nLABEL bf-ci.roundtrip="%s"\n' "$BASE_IMAGE" "$run_id" > "$build_dir/Dockerfile"
local_images+=("$staging")
docker build -t "$staging" "$build_dir"
docker push "$staging" >/dev/null
d1=$(docker inspect --format '{{index .RepoDigests 0}}' "$staging" | sed 's/^[^@]*@//')
[[ $d1 =~ ^sha256:[0-9a-f]{64}$ ]] || fail "could not read the pushed digest"

# Resolves a tag the way cd.yml's image-state step does (cd_release.py image_state), with the registry guard widened.
resolve_tag() {
  python3 -I - "$cd_release" "$prefix" "$1" <<'PY'
import importlib.util
import re
import sys

path, prefix, ref = sys.argv[1:4]
spec = importlib.util.spec_from_file_location("cd_release", path)
cd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cd)
cd.IMAGE_REF_RE = re.compile(re.escape(prefix) + r"@sha256:[0-9a-f]{64}")
cd.IMAGE_TAG_REF_RE = re.compile(re.escape(prefix) + ":" + cd.TAG_RE.pattern)
state, digest = cd.image_state(ref, cd.system_runner)
print(state, digest or "none")
PY
}

# The same check as cd.yml's confirm-release step (cd_release.py confirm_release_digest), with the registry guard widened.
confirm_tag() {
  python3 -I - "$cd_release" "$prefix" "$1" "$2" <<'PY'
import importlib.util
import re
import sys

path, prefix, ref, attested = sys.argv[1:5]
spec = importlib.util.spec_from_file_location("cd_release", path)
cd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cd)
cd.IMAGE_REF_RE = re.compile(re.escape(prefix) + r"@sha256:[0-9a-f]{64}")
cd.IMAGE_TAG_REF_RE = re.compile(re.escape(prefix) + ":" + cd.TAG_RE.pattern)
try:
    print(cd.confirm_release_digest(ref, attested, cd.system_runner))
except cd.CdError as exc:
    print(f"::error::{exc}", file=sys.stderr)
    sys.exit(1)
PY
}

# Release tag with the flag the CD workflow uses. The release tag must resolve to exactly the attested digest.
docker buildx imagetools create --prefer-index=false --tag "$release_ref" "$prefix@$d1" >/dev/null
read -r state digest < <(resolve_tag "$release_ref")
[[ $state == present ]] || fail "release tag is missing after imagetools create"
[[ $digest == "$d1" ]] || fail "release tag resolves to $digest, not the pushed $d1"
confirm_tag "$release_ref" "$d1" >/dev/null || fail "confirm_release_digest rejected the release tag"
echo "PASS roundtrip: release tag keeps the attested digest"

# Control, informational: the same command without the flag. It documents what Docker's default does on this runner.
docker buildx imagetools create --tag "$control_ref" "$prefix@$d1" >/dev/null
read -r control_state control_digest < <(resolve_tag "$control_ref")
[[ $control_state == present ]] || fail "control tag is missing after imagetools create"
if [[ $control_digest == "$d1" ]]; then
  echo "INFO control: default imagetools create digest same"
else
  echo "INFO control: default imagetools create digest changed ($control_digest)"
fi
