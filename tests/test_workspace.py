from __future__ import annotations

import os
from pathlib import Path

import pytest

from secureyourcode.config import ConfigError, load_settings, validate_server_auth, validate_state_dir
from secureyourcode.workspace import (
    LayoutError,
    WorkspaceError,
    compute_fingerprint,
    list_source_files,
    repo_hash,
    resolve_in_root,
    stage_source,
    validate_demo_layout,
)

from .conftest import APP_ROOT, DEMO


def test_fingerprint_is_lf_normalised_and_path_sensitive(tmp_outside: Path) -> None:
    a, b = tmp_outside / "a", tmp_outside / "b"
    a.mkdir()
    b.mkdir()
    (a / "X.cs").write_bytes(b"class X {}\nclass Y {}\n")
    (b / "X.cs").write_bytes(b"class X {}\r\nclass Y {}\r\n")
    assert compute_fingerprint(a) == compute_fingerprint(b)
    (b / "X.cs").rename(b / "Z.cs")
    assert compute_fingerprint(a) != compute_fingerprint(b)


def test_selection_excludes_build_outputs_git_and_secrets(tmp_outside: Path) -> None:
    root = tmp_outside / "r"
    for rel in ["A.cs", "bin/B.cs", "obj/C.cs", ".git/D.cs", "graphify-out/graph.json", ".env", "secrets.json", "appsettings.json", "notes.txt"]:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
    assert list_source_files(root) == ["A.cs", "appsettings.json"]


def test_symlink_escape_is_refused(tmp_outside: Path) -> None:
    root = tmp_outside / "r"
    root.mkdir()
    outside = tmp_outside / "secret.cs"
    outside.write_text("class S {}")
    os.symlink(outside, root / "Link.cs")
    with pytest.raises(WorkspaceError):
        list_source_files(root)


def test_stage_syncs_changes_and_deletions_without_touching_input(demo_copy: Path, tmp_outside: Path) -> None:
    before = {p: p.read_bytes() for p in demo_copy.rglob("*") if p.is_file()}
    dest = tmp_outside / "snap"
    first = stage_source(demo_copy, dest)
    assert first.copied == len(first.files) and not first.source_changed
    assert first.fingerprint == compute_fingerprint(demo_copy)

    again = stage_source(demo_copy, dest)
    assert again.copied == 0 and again.fingerprint == first.fingerprint

    (demo_copy / "Program.cs").write_text((demo_copy / "Program.cs").read_text() + "\n// marker\n")
    (demo_copy / "Services/SessionStore.cs").unlink()
    third = stage_source(demo_copy, dest)
    assert third.copied == 1 and third.removed == 1
    assert not (dest / "Services/SessionStore.cs").exists()
    assert third.fingerprint != first.fingerprint
    # input files other than our own edits are byte-identical
    for p, data in before.items():
        if p.name not in ("Program.cs", "SessionStore.cs"):
            assert p.read_bytes() == data


def test_demo_layout_validation(demo_copy: Path) -> None:
    assert validate_demo_layout(demo_copy).name == "DemoShop.csproj"
    proj = demo_copy / "DemoShop.csproj"
    original = proj.read_text()
    proj.write_text(original.replace("</Project>", '<ItemGroup><PackageReference Include="X" Version="1.0" /></ItemGroup></Project>'))
    with pytest.raises(LayoutError, match="PackageReference"):
        validate_demo_layout(demo_copy)
    proj.write_text(original)
    (demo_copy / "Directory.Build.props").write_text("<Project/>")
    with pytest.raises(LayoutError, match="MSBuild"):
        validate_demo_layout(demo_copy)
    (demo_copy / "Directory.Build.props").unlink()
    proj.write_text(original.replace("net10.0", "net8.0"))
    with pytest.raises(LayoutError, match="net10.0"):
        validate_demo_layout(demo_copy)


def test_resolve_in_root_refuses_traversal(tmp_outside: Path) -> None:
    root = tmp_outside / "r"
    (root / "A").mkdir(parents=True)
    (root / "A/X.cs").write_text("x")
    assert resolve_in_root(root, "A\\X.cs").name == "X.cs"
    for bad in ["../r/A/X.cs", "/etc/passwd", "C:/Windows/x.cs", "A/../../x.cs", "", "A/missing.cs"]:
        with pytest.raises(WorkspaceError):
            resolve_in_root(root, bad)


def test_repo_hash_is_path_identity() -> None:
    assert repo_hash(DEMO) == repo_hash(DEMO / "." ) and len(repo_hash(DEMO)) == 16


def test_state_dir_must_be_outside_both_repos(tmp_outside: Path) -> None:
    env = {"STATE_DIR": str(APP_ROOT / "state"), "REPO_ROOT": str(DEMO)}
    with pytest.raises(ConfigError):
        validate_state_dir(load_settings(env_file=tmp_outside / "none", environ=env))
    env = {"STATE_DIR": str(tmp_outside / "s"), "REPO_ROOT": str(tmp_outside)}
    with pytest.raises(ConfigError):
        validate_state_dir(load_settings(env_file=tmp_outside / "none", environ=env))
    env = {"STATE_DIR": str(tmp_outside / "s"), "REPO_ROOT": str(DEMO)}
    validate_state_dir(load_settings(env_file=tmp_outside / "none", environ=env))


def test_config_precedence_env_over_dotenv(tmp_outside: Path) -> None:
    env_file = tmp_outside / ".env"
    env_file.write_text("GEMINI_MODEL=from-file\nGOOGLE_CLOUD_PROJECT=file-project\nSCAN_TIMEOUT_SECONDS=111\n")
    s = load_settings(env_file=env_file, environ={"GEMINI_MODEL": "from-env"})
    assert s.gemini_model == "from-env" and s.google_cloud_project == "file-project" and s.scan_timeout_seconds == 111
    s = load_settings(env_file=tmp_outside / "missing", environ={})
    assert s.gemini_model is None
    with pytest.raises(ConfigError, match="GEMINI_MODEL"):
        s.require_model()
    placeholder = load_settings(env_file=tmp_outside / "missing", environ={"GEMINI_MODEL": "REPLACE_WITH_VERIFIED_MODEL_ID", "GOOGLE_CLOUD_PROJECT": "p"})
    with pytest.raises(ConfigError, match="GEMINI_MODEL"):
        placeholder.require_model()


def test_server_auth_rules(tmp_outside: Path) -> None:
    none = tmp_outside / "none"
    with pytest.raises(ConfigError, match="placeholder"):
        validate_server_auth(load_settings(none, {"SERVICE_TOKEN": "REPLACE_WITH_LONG_RANDOM_TOKEN"}), "127.0.0.1")
    with pytest.raises(ConfigError, match="32"):
        validate_server_auth(load_settings(none, {"SERVICE_TOKEN": "short"}), "127.0.0.1")
    with pytest.raises(ConfigError, match="non-loopback"):
        validate_server_auth(load_settings(none, {"ALLOW_UNAUTHENTICATED_LOOPBACK": "true"}), "0.0.0.0")
    with pytest.raises(ConfigError, match="ALLOW_UNAUTHENTICATED_LOOPBACK"):
        validate_server_auth(load_settings(none, {}), "127.0.0.1")
    validate_server_auth(load_settings(none, {"ALLOW_UNAUTHENTICATED_LOOPBACK": "true"}), "127.0.0.1")
    validate_server_auth(load_settings(none, {"SERVICE_TOKEN": "x" * 40}), "0.0.0.0")


def test_public_anonymous_access_requires_explicit_opt_in(tmp_outside: Path) -> None:
    none = tmp_outside / "none"
    validate_server_auth(load_settings(none, {"ALLOW_UNAUTHENTICATED_PUBLIC": "true"}), "0.0.0.0")
    with pytest.raises(ConfigError, match="non-loopback"):
        validate_server_auth(load_settings(none, {"ALLOW_UNAUTHENTICATED_PUBLIC": "false"}), "0.0.0.0")
    with pytest.raises(ConfigError, match="32"):
        validate_server_auth(load_settings(none, {"ALLOW_UNAUTHENTICATED_PUBLIC": "true", "SERVICE_TOKEN": "short"}), "0.0.0.0")
