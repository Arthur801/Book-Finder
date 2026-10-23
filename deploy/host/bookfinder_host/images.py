"""Image reference rules shared by the manifest, runtime and config code.

Why: a tag can move to different bytes after a release is recorded, so every image the host touches must be named by
its digest. Repository names are checked too, so a tag cannot be smuggled into WEB_IMAGE_REPOSITORY.
"""

import re

_REPOSITORY = r"(?:[a-z0-9.-]+(?::[0-9]+)?/)?[a-z0-9][a-z0-9._-]*(?:/[a-z0-9][a-z0-9._-]*)*"
REPOSITORY_RE = re.compile(_REPOSITORY)
DIGEST_REF_RE = re.compile(_REPOSITORY + r"@sha256:[0-9a-f]{64}")


def is_digest_ref(reference: str) -> bool:
    """True only for "<repository>@sha256:<64 hex>"; a tag, even with a digest suffix, is rejected."""
    return DIGEST_REF_RE.fullmatch(reference) is not None


def is_repository(reference: str) -> bool:
    return REPOSITORY_RE.fullmatch(reference) is not None
