"""Where texts come from: the packet tool's information-in socket.

The editorial packet never reads a hard-coded path. It asks a *source* for a
text by name. Today there is one kind of source, a folder on disk (usually the
content folder named by the ``PROSPERO_HOME`` environment variable). Later, the
same interface can be backed by an MCP information-in resource (decision
DEC-177) without the packet code changing.

Why a folder adapter and not just ``open()``: Zach's own works live outside this
repository (DEC-183, DEC-184). Routing every read through one small class gives
one place to enforce "stay inside the folder you were given" and one place to
swap in another backend.
"""

from __future__ import annotations

import os
from pathlib import Path


class SourceError(Exception):
    """A text could not be read from a source (missing, or outside the source)."""


def _resolve(path: Path, name: str) -> Path:
    """``path.resolve()``, with a symlink loop or an OS error reported as a
    ``SourceError`` (Codex review on #9: on Python 3.10-3.12 a loop raises
    ``RuntimeError``, which would escape every caller)."""
    try:
        return path.resolve()
    except (RuntimeError, OSError) as error:
        raise SourceError(f"{name!r} can't be resolved (a symlink loop?): {error}") from error


class Source:
    """The interface every source implements.

    A source has a ``name`` (used in locators, so a reader can tell where a
    quotation came from) and one method, ``read(name)``, that returns the text
    stored under that name as a ``str``.
    """

    name = "source"

    def read(self, name: str) -> str:  # pragma: no cover - interface only
        raise NotImplementedError


class FolderSource(Source):
    """Read UTF-8 texts from one folder, refusing anything outside it.

    ``name`` arguments are paths relative to the folder. A name that resolves
    outside the folder (``../x``, an absolute path, a symlink pointing out) is
    refused, so a packet spec can never make the tool read an arbitrary file.
    """

    def __init__(self, root: str | os.PathLike, label: str | None = None):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise SourceError(f"source folder does not exist: {self.root}")
        # The label appears in locators. Default to the folder's own name rather
        # than its full path, so packets don't leak where content lives on disk.
        self.name = label or self.root.name

    def path_of(self, name: str) -> Path:
        """Return the real path for ``name``, or raise if it leaves the folder."""
        candidate = _resolve(self.root / name, name)
        if candidate != self.root and self.root not in candidate.parents:
            raise SourceError(f"{name!r} is outside the source folder")
        if not candidate.is_file():
            raise SourceError(f"{name!r} not found in source {self.name!r}")
        return candidate

    def canonical(self, name: str) -> str:
        """The one spelling of ``name`` used in records: relative to the
        folder, ``/``-separated, with ``./`` and ``..`` folded away. Raises
        ``SourceError`` like ``path_of`` when the file isn't there."""
        return self.path_of(name).relative_to(self.root).as_posix()

    def names(self, folder: str, pattern: str) -> list[str]:
        """Names (relative to the source, ``/``-separated) of entries matching
        ``pattern`` directly in ``folder``, sorted. Nothing is opened here. A
        name may still fail ``path_of`` or ``read`` (a dangling symlink, or one
        pointing out of the source); it is listed anyway so the caller can
        report it rather than have it vanish (Codex review on #9). An absent
        folder has no names; one that exists but isn't a folder, or leads out
        of the source, raises ``SourceError``."""
        base = self.root / folder
        if not os.path.lexists(base):
            return []
        # Containment first, so a packets/ symlinked out of the source is
        # refused before anything there is listed (Copilot review on #9).
        real = _resolve(base, folder)
        if real != self.root and self.root not in real.parents:
            raise SourceError(f"{folder!r} points outside the source folder")
        if not real.is_dir():
            raise SourceError(f"{folder!r} exists but is not a folder (or is a broken link)")
        return [f"{folder}/{path.name}" for path in sorted(real.glob(pattern))]

    def read(self, name: str) -> str:
        # newline="" keeps the bytes as they are (no \r\n translation), so the
        # hash of what we read matches the hash of the file on disk.
        with open(self.path_of(name), encoding="utf-8", newline="") as handle:
            return handle.read()


def content_home(explicit: str | os.PathLike | None = None) -> Path:
    """The content folder: an explicit argument, else ``$PROSPERO_HOME``.

    There is deliberately no default. Guessing a folder could put Zach's
    writing somewhere he didn't choose, or inside this repository.
    """
    chosen = explicit or os.environ.get("PROSPERO_HOME")
    if not chosen:
        raise SourceError("no content folder: pass one explicitly or set PROSPERO_HOME")
    return Path(chosen).resolve()
