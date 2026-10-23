#!/usr/bin/env bash
# Round-trip check for the CD release-tag steps (#92): `docker buildx imagetools create` must keep the attested digest.
#
# What is real: a throwaway registry:2 container, a single-platform image built and pushed the way cd.yml does it
# (docker build, docker push, digest from RepoDigests), buildx imagetools, and the digest resolution in
# .github/scripts/cd_release.py (image_state and confirm_release_digest), called directly from this script.
# The only thing changed is the registry name guard: cd_release.py admits only the ghcr.io CD repositories, so the
# script widens that regex to the local registry prefix and nothing else.
#
# Two source shapes are covered, because Docker decides the shape of a pushed image:
#   index:    an OCI image index (amd64 manifest + attestation manifest). The check is the cd.yml command with
#             --prefer-index=false, and the control is the same command without the flag.
#   manifest: a single image manifest, the child of that index for linux/amd64. This is the shape that the default
#             --prefer-index=true would wrap in a new index. The control asserts that wrap happens; if Docker does not
#             wrap, the script prints WARN instead of failing.
# Which shape `docker push` produced here is printed as "INFO source shape". When the push already gives a single
# manifest (as a classic image store may), the index case is skipped with an INFO line.
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
# Tags must match cd_release.py's TAG_RE (vX.Y.Z), so each case gets its own version.
INDEX_RELEASE_TAG="v0.0.0"
INDEX_CONTROL_TAG="v0.0.1"
SINGLE_RELEASE_TAG="v0.0.2"
SINGLE_CONTROL_TAG="v0.0.3"

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

# Same build and digest method as cd.yml: docker build, docker push, then the first RepoDigest of the pushed image.
build_dir=$(mktemp -d)
printf 'FROM %s\nLABEL bf-ci.roundtrip="%s"\n' "$BASE_IMAGE" "$run_id" > "$build_dir/Dockerfile"
local_images+=("$staging")
docker build -t "$staging" "$build_dir"
docker push "$staging" >/dev/null
d1=$(docker inspect --format '{{index .RepoDigests 0}}' "$staging" | sed 's/^[^@]*@//')
[[ $d1 =~ ^sha256:[0-9a-f]{64}$ ]] || fail "could not read the pushed digest"

# Raw manifest helpers. `imagetools inspect --raw` returns the manifest bytes of a ref, index or not.
raw_manifest() {
  docker buildx imagetools inspect --raw "$1"
}

media_type_of() {
  raw_manifest "$1" | python3 -I -c 'import json, sys; print(json.load(sys.stdin)["mediaType"])'
}

is_index() {
  [[ $1 == *index* || $1 == *manifest.list* ]]
}

# The linux/amd64 child of an index. Attestation entries (unknown/unknown) are skipped; anything but exactly one match fails.
amd64_child() {
  raw_manifest "$1" | python3 -I -c '
import json
import sys

index = json.load(sys.stdin)
matches = [
    m["digest"]
    for m in index.get("manifests", [])
    if m.get("platform", {}).get("architecture") == "amd64" and m.get("platform", {}).get("os") == "linux"
]
if len(matches) != 1:
    sys.exit(1)
print(matches[0])
'
}

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

# Which shape did docker push produce? Printed so the CI log shows what the runner produces.
d1_media=$(media_type_of "$prefix@$d1")
if is_index "$d1_media"; then
  shape=index
else
  shape=manifest
fi
echo "INFO source shape: $shape"

if [[ $shape == index ]]; then
  # Index case: the cd.yml command with the flag must keep the index digest, and the control shows the default.
  docker buildx imagetools create --prefer-index=false --tag "$prefix:$INDEX_RELEASE_TAG" "$prefix@$d1" >/dev/null
  read -r state digest < <(resolve_tag "$prefix:$INDEX_RELEASE_TAG")
  [[ $state == present ]] || fail "release tag is missing after imagetools create"
  [[ $digest == "$d1" ]] || fail "release tag resolves to $digest, not the pushed $d1"
  confirm_tag "$prefix:$INDEX_RELEASE_TAG" "$d1" >/dev/null || fail "confirm_release_digest rejected the release tag"
  echo "PASS roundtrip: release tag keeps the attested digest"

  docker buildx imagetools create --tag "$prefix:$INDEX_CONTROL_TAG" "$prefix@$d1" >/dev/null
  read -r control_state control_digest < <(resolve_tag "$prefix:$INDEX_CONTROL_TAG")
  [[ $control_state == present ]] || fail "control tag is missing after imagetools create"
  if [[ $control_digest == "$d1" ]]; then
    echo "INFO control: default imagetools create digest same"
  else
    echo "INFO control: default imagetools create digest changed ($control_digest)"
  fi

  # The single-manifest source is the amd64 child of this index.
  single_source=$(amd64_child "$prefix@$d1") || fail "the pushed index has no single linux/amd64 manifest"
else
  echo "INFO index case skipped: docker push already produced a single manifest"
  single_source=$d1
fi

# Single-manifest case: the source is one image manifest, so --prefer-index=false must keep that manifest's digest.
single_source_ref="$prefix@$single_source"
single_source_media=$(media_type_of "$single_source_ref")
is_index "$single_source_media" && fail "the single-manifest source is an index ($single_source_media)"

docker buildx imagetools create --prefer-index=false --tag "$prefix:$SINGLE_RELEASE_TAG" "$single_source_ref" >/dev/null
read -r state digest < <(resolve_tag "$prefix:$SINGLE_RELEASE_TAG")
[[ $state == present ]] || fail "single-manifest release tag is missing after imagetools create"
[[ $digest == "$single_source" ]] || fail "single-manifest release tag resolves to $digest, not the source $single_source"
confirm_tag "$prefix:$SINGLE_RELEASE_TAG" "$single_source" >/dev/null || fail "confirm_release_digest rejected the single-manifest release tag"
single_release_media=$(media_type_of "$prefix:$SINGLE_RELEASE_TAG")
[[ $single_release_media == "$single_source_media" ]] \
  || fail "media type changed from $single_source_media to $single_release_media"
echo "PASS single-manifest: --prefer-index=false keeps the digest"

# Control: the default wraps a single manifest into a new index, which is the bug the flag prevents.
docker buildx imagetools create --tag "$prefix:$SINGLE_CONTROL_TAG" "$single_source_ref" >/dev/null
read -r control_state control_digest < <(resolve_tag "$prefix:$SINGLE_CONTROL_TAG")
[[ $control_state == present ]] || fail "single-manifest control tag is missing after imagetools create"
control_media=$(media_type_of "$prefix:$SINGLE_CONTROL_TAG")
if [[ $control_digest == "$single_source" ]]; then
  echo "WARN control: default imagetools create kept the single-manifest digest on this Docker; the wrap did not happen"
else
  is_index "$control_media" || fail "default create changed the digest but did not produce an index ($control_media)"
  echo "PASS control: default create wraps a single manifest into a new index"
fi
