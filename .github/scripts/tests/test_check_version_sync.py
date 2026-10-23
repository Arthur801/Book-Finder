import check_version_sync

GLOBAL_JSON = '{\n  "sdk": {\n    "version": "10.0.113",\n    "rollForward": "latestPatch"\n  }\n}\n'
DOCKERFILE_HEADER = "# Build SDK is pinned by ARG; keep it equal to global.json and the ADD --checksum.\n"


def make_root(tmp_path, dockerfile_text):
    (tmp_path / "global.json").write_text(GLOBAL_JSON, encoding="utf-8")
    if dockerfile_text is not None:
        (tmp_path / "Dockerfile").write_text(dockerfile_text, encoding="utf-8")
    return tmp_path


def test_dockerfile_sdk_matching_global_json_passes(tmp_path):
    root = make_root(tmp_path, DOCKERFILE_HEADER + "ARG DOTNET_SDK_VERSION=10.0.113\nFROM scratch\n")

    assert check_version_sync.check_dockerfile_sdk_matches_global_json(root) == []


def test_dockerfile_sdk_mismatch_names_both_files(tmp_path):
    root = make_root(tmp_path, "ARG DOTNET_SDK_VERSION=10.0.114\nFROM scratch\n")

    errors = check_version_sync.check_dockerfile_sdk_matches_global_json(root)

    assert len(errors) == 1
    assert "Dockerfile" in errors[0]
    assert "global.json" in errors[0]
    assert "10.0.114" in errors[0]
    assert "10.0.113" in errors[0]
    assert "--checksum" in errors[0]


def test_dockerfile_without_sdk_arg_is_rejected(tmp_path):
    root = make_root(tmp_path, "FROM scratch\n")

    errors = check_version_sync.check_dockerfile_sdk_matches_global_json(root)

    assert len(errors) == 1
    assert "ARG DOTNET_SDK_VERSION" in errors[0]


def test_missing_dockerfile_is_rejected(tmp_path):
    root = make_root(tmp_path, None)

    errors = check_version_sync.check_dockerfile_sdk_matches_global_json(root)

    assert len(errors) == 1
    assert "Dockerfile" in errors[0]
