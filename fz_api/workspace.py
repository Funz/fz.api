"""Workspace and cwd-safety helpers.

HTTP clients don't share the server's filesystem, so file-based fz operations
receive their input files inline (a ``{relative_path: text_content}`` mapping).
Each request materializes those files into an isolated temporary directory.

fz core functions call ``os.chdir`` on the *process* (they restore it on exit),
so concurrent invocations would race on the global working directory. All fz
calls are therefore serialized through :data:`FZ_LOCK`. This keeps the server
correct at the cost of running one fz operation at a time; scale horizontally
by running multiple server instances.
"""

import os
import shutil
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Process-wide lock guarding every fz core call (they mutate global cwd).
FZ_LOCK = threading.Lock()

# Upper bound on returned inline file trees, to avoid unbounded responses.
MAX_INLINE_FILE_BYTES = 1_000_000


class WorkspaceError(ValueError):
    """Raised for invalid workspace inputs (e.g. path traversal)."""


def _safe_join(root: Path, relative: str) -> Path:
    """Join ``relative`` under ``root``, rejecting escapes via ``..`` or absolutes."""
    candidate = (root / relative).resolve()
    root_resolved = root.resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise WorkspaceError(f"Illegal path outside workspace: {relative!r}")
    return candidate


@contextmanager
def workspace(input_files: Optional[Dict[str, str]] = None):
    """Create a temp directory, write ``input_files`` into it, and clean up.

    Yields the workspace :class:`~pathlib.Path`.
    """
    tmp = Path(tempfile.mkdtemp(prefix="fzapi-"))
    try:
        for rel, content in (input_files or {}).items():
            dest = _safe_join(tmp, rel)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content if content is not None else "", encoding="utf-8")
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def resolve_input_path(
    root: Path, input_files: Dict[str, str], input_path: Optional[str]
) -> Path:
    """Determine the fz ``input_path`` inside the workspace.

    - explicit ``input_path`` (relative) wins if provided
    - a single uploaded file -> that file
    - otherwise -> the workspace directory itself
    """
    if input_path:
        return _safe_join(root, input_path)
    names = list((input_files or {}).keys())
    if len(names) == 1:
        return _safe_join(root, names[0])
    return root


def collect_file_tree(
    root: Path, exclude: Optional[List[Path]] = None
) -> Tuple[Dict[str, str], List[str]]:
    """Read a directory tree into a ``{relative_path: text_content}`` mapping.

    Returns ``(files, skipped)`` where ``skipped`` lists paths omitted because
    they were binary or exceeded :data:`MAX_INLINE_FILE_BYTES`.
    """
    exclude_set = {p.resolve() for p in (exclude or [])}
    files: Dict[str, str] = {}
    skipped: List[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.resolve() in exclude_set:
            continue
        rel = str(path.relative_to(root))
        try:
            if path.stat().st_size > MAX_INLINE_FILE_BYTES:
                skipped.append(rel)
                continue
            files[rel] = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            skipped.append(rel)
    return files, skipped


@contextmanager
def pushd(path: Path):
    """Temporarily change the process working directory (used under FZ_LOCK)."""
    prev = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prev)
