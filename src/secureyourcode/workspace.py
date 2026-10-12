"""Source staging, fingerprints, demo layout validation and safe path resolution."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

SOURCE_SUFFIXES = {".cs", ".csproj", ".sln", ".slnx", ".json"}
EXCLUDED_DIRS = {".git", "bin", "obj", ".vs", ".vscode", ".idea", "graphify-out", "node_modules", "TestResults"}
EXCLUDED_FILE_PATTERNS = (
    re.compile(r"^\.env(\..*)?$", re.IGNORECASE),
    re.compile(r"^secrets?\.json$", re.IGNORECASE),
    re.compile(r"^appsettings\.(development|local|secrets?)\.json$", re.IGNORECASE),
    re.compile(r".*\.(pfx|p12|key|pem|snk)$", re.IGNORECASE),
    re.compile(r"^application_default_credentials\.json$", re.IGNORECASE),
)
FORBIDDEN_BUILD_FILES = {"Directory.Build.props", "Directory.Build.targets", "Directory.Build.rsp", "Directory.Packages.props"}


class WorkspaceError(RuntimeError):
    pass


class LayoutError(WorkspaceError):
    pass


def repo_hash(repo_root: Path) -> str:
    """Local graph-cache identity only; not a source fingerprint or security identity."""
    return hashlib.sha256(str(Path(repo_root).resolve()).encode("utf-8")).hexdigest()[:16]


def normalize_text(data: bytes) -> bytes:
    """LF-normalised content used for fingerprints (Windows/Linux checkouts agree)."""
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _is_excluded_file(name: str) -> bool:
    return any(p.match(name) for p in EXCLUDED_FILE_PATTERNS)


def list_source_files(root: Path, extra_excluded_dirs: tuple[Path, ...] = ()) -> list[str]:
    """Canonical forward-slash relative paths of selected source files, sorted.

    Raises WorkspaceError when a symlink escapes the root.
    """
    root = Path(root).resolve()
    excluded = [Path(p).resolve() for p in extra_excluded_dirs]
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        kept = []
        for d in dirnames:
            full = current / d
            if d in EXCLUDED_DIRS or any(_within(full.resolve(), e) for e in excluded):
                continue
            if full.is_symlink():
                target = full.resolve()
                if not _within(target, root):
                    raise WorkspaceError(f"Symlinked directory escapes the repository: {full.relative_to(root).as_posix()}")
                continue  # in-root directory links are not followed (avoid duplicate content)
            kept.append(d)
        dirnames[:] = sorted(kept)
        for name in sorted(filenames):
            full = current / name
            if Path(name).suffix.lower() not in SOURCE_SUFFIXES or _is_excluded_file(name):
                continue
            if full.is_symlink() and not _within(full.resolve(), root):
                raise WorkspaceError(f"Symlinked file escapes the repository: {full.relative_to(root).as_posix()}")
            files.append(full.relative_to(root).as_posix())
    return sorted(files)


def _within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def compute_fingerprint(root: Path, files: list[str] | None = None) -> str:
    """The single source-fingerprint helper (staging, report and demo-evaluate all use it)."""
    root = Path(root).resolve()
    files = list_source_files(root) if files is None else sorted(files)
    digest = hashlib.sha256()
    for rel in files:
        content = normalize_text((root / rel).read_bytes())
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(len(content)).encode("ascii"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return digest.hexdigest()


def validate_demo_layout(repo_root: Path) -> Path:
    """Accept only the trusted DemoShop-style layout. Not a sandbox and not a trust proof."""
    root = Path(repo_root).resolve()
    if not root.is_dir():
        raise LayoutError(f"Repository root does not exist or is not a directory: {root}")
    projects = [p for p in list_source_files(root) if p.endswith(".csproj")]
    if len(projects) != 1:
        raise LayoutError(f"Expected exactly one .csproj, found {len(projects)}: {projects}")
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        hits = FORBIDDEN_BUILD_FILES.intersection(filenames)
        if hits:
            raise LayoutError(f"Custom MSBuild files are not allowed in the demo layout: {sorted(hits)}")
    project = root / projects[0]
    text = project.read_text(encoding="utf-8-sig")
    if "<PackageReference" in text:
        raise LayoutError("The demo project must have zero <PackageReference> items.")
    if re.search(r"<Import\b", text) or re.search(r"<UsingTask\b", text) or re.search(r"<Target\b", text):
        raise LayoutError("Custom MSBuild imports, tasks or targets are not allowed in the demo project.")
    tfm = re.search(r"<TargetFramework>\s*([^<]+?)\s*</TargetFramework>", text)
    if not tfm or tfm.group(1) != "net10.0" or "<TargetFrameworks>" in text:
        raise LayoutError("The demo project must target exactly net10.0.")
    return project


@dataclass
class StageResult:
    files: list[str]
    fingerprint: str
    source_changed: bool
    copied: int
    removed: int


def stage_source(repo_root: Path, dest: Path) -> StageResult:
    """Synchronise selected files from the (never modified) input repo into the stable snapshot.

    Unchanged files are left untouched so Graphify's incremental manifest sees only real changes.
    """
    repo_root = Path(repo_root).resolve()
    dest = Path(dest)
    before = compute_fingerprint(repo_root)
    files = list_source_files(repo_root)
    dest.mkdir(parents=True, exist_ok=True)
    copied = 0
    for rel in files:
        src = repo_root / rel
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        data = src.read_bytes()
        if target.is_file() and not target.is_symlink() and target.read_bytes() == data:
            continue
        if target.is_symlink():
            target.unlink()
        tmp = target.with_name(target.name + ".syc-tmp")
        tmp.write_bytes(data)
        os.replace(tmp, target)
        copied += 1
    wanted = set(files)
    removed = 0
    for dirpath, dirnames, filenames in os.walk(dest, topdown=False):
        for name in filenames:
            full = Path(dirpath) / name
            rel = full.relative_to(dest).as_posix()
            if rel not in wanted:
                full.unlink()
                removed += 1
        for d in dirnames:
            full = Path(dirpath) / d
            if full.is_dir() and not any(full.iterdir()):
                full.rmdir()
    staged_fp = compute_fingerprint(dest, files)
    after = compute_fingerprint(repo_root)
    changed = before != after or staged_fp != after
    return StageResult(files=files, fingerprint=staged_fp, source_changed=changed, copied=copied, removed=removed)


def make_build_copy(staged: Path, dest: Path) -> None:
    """Disposable per-scan copy for Roslyn; the frozen snapshot itself is never built."""
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(staged, dest, symlinks=False)


def resolve_in_root(root: Path, rel: str) -> Path:
    """Resolve a repo-relative path under root, refusing traversal, absolute paths and symlink escape."""
    if not rel or "\x00" in rel:
        raise WorkspaceError("Empty or invalid path.")
    rel = rel.replace("\\", "/").strip()
    if rel.startswith("/") or re.match(r"^[A-Za-z]:", rel):
        raise WorkspaceError(f"Absolute paths are not allowed: {rel}")
    root = Path(root).resolve()
    candidate = (root / rel).resolve()
    if not _within(candidate, root):
        raise WorkspaceError(f"Path escapes the source root: {rel}")
    if not candidate.is_file():
        raise WorkspaceError(f"No such source file: {rel}")
    return candidate


def canonical_rel(root: Path, rel: str) -> str:
    return resolve_in_root(root, rel).relative_to(Path(root).resolve()).as_posix()


def read_lines(path: Path) -> list[str]:
    return normalize_text(path.read_bytes()).decode("utf-8", errors="replace").split("\n")
