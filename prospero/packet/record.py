"""Write a packet out, and record Zach's decision on it.

Both write only into the content folder, never into this repository
(DEC-183, DEC-184): a packet contains the original text, which may be Zach's
own unpublished writing.

The decision log follows the pattern Today uses: one JSON object per line,
appended, never rewritten, so the history of accept / reject / revise calls
survives and can be read back in order.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .build import Packet, sha256
from .sources import Source

# The repository root: two levels above this file (prospero/packet/record.py).
REPO_ROOT = Path(__file__).resolve().parents[2]

DECISIONS = ("accept", "reject", "revise")
DECISION_LOG = "decisions.jsonl"


class RecordError(Exception):
    """A packet or decision could not be written."""


def _outside_repo(folder: Path) -> Path:
    """Refuse a folder inside this repository; content must never land here."""
    folder = folder.resolve()
    if folder == REPO_ROOT or REPO_ROOT in folder.parents:
        raise RecordError(f"refusing to write content inside the repository: {folder}")
    return folder


def render_markdown(packet: Packet) -> str:
    """A readable view of the packet. The JSON beside it is the record."""
    lines = [f"# Editorial packet: {packet.edition_name}", ""]
    lines.append(f"Checks: {'all passed' if packet.ok else 'FAILED'}")
    for check in packet.checks:
        lines.append(f"- {'ok' if check.ok else 'FAIL'} {check.name}")
        lines.extend(f"  - {problem}" for problem in check.problems)
    lines += ["", f"## Original ({packet.original_name}, sha256 {packet.original_sha256[:12]}…)", "",
              packet.original.rstrip("\n"), "",
              f"## Edition ({packet.edition_name})", "", packet.edition.rstrip("\n"), "", "## Changes", ""]
    for change in packet.changes:
        lines.append(f"- **{change['id']}** [{change['kind']}] {change['rationale']}")
        if change["original_text"]:
            lines.append(f"  - was: {change['original_text']}")
        if change["edition_text"]:
            lines.append(f"  - now: {change['edition_text']}")
    lines += ["", "## Quotations", ""]
    for quote in packet.quotations:
        loc = quote["locator"]
        who = f"{quote['speaker']}, " if quote.get("speaker") else ""
        lines.append(f"- “{quote['text']}” ({who}{loc['name']} line {loc['line']})")
    return "\n".join(lines) + "\n"


def write_packet(packet: Packet, out_dir: str | Path, stem: str) -> tuple[Path, Path]:
    """Write ``<stem>.packet.json`` and ``<stem>.packet.md`` into ``out_dir``.

    Existing files are not overwritten: a packet is a record of what was
    proposed, and a new proposal gets a new stem.
    """
    # A stem is a bare file name. A separator, an absolute path or ".." could
    # carry the packet (and the original inside it) out of the checked folder,
    # for instance into this repository.
    if stem in ("", ".", "..") or "/" in stem or "\\" in stem or Path(stem).name != stem:
        raise RecordError(f"stem must be a plain file name, not {stem!r}")
    folder = _outside_repo(Path(out_dir))
    json_path, md_path = folder / f"{stem}.packet.json", folder / f"{stem}.packet.md"
    for path in (json_path, md_path):
        if path.resolve().parent != folder:
            raise RecordError(f"{path.name} would land outside {folder}")
    folder.mkdir(parents=True, exist_ok=True)
    for path in (json_path, md_path):
        # lexists, not exists: a dangling symlink would otherwise be followed.
        if os.path.lexists(path):
            raise RecordError(f"{path.name} already exists; use a new stem")
    # Mode "x" creates the file or fails; it never follows a symlink planted
    # between the check above and the write.
    try:
        with open(json_path, "x", encoding="utf-8") as handle:
            handle.write(json.dumps(packet.to_dict(), ensure_ascii=False, indent=2) + "\n")
        with open(md_path, "x", encoding="utf-8") as handle:
            handle.write(render_markdown(packet))
    except FileExistsError as error:
        raise RecordError(f"{Path(error.filename).name} already exists; use a new stem") from error
    return json_path, md_path


def _open_log(folder: Path, original: Path | None):
    """Open the decision log for appending, refusing a symlink or an alias.

    A symlinked decisions.jsonl could point at the original (so even a
    ``reject`` would change it) or into this repository. The log must be a
    regular file directly in ``folder`` and must not be the original.
    """
    log = folder / DECISION_LOG
    if log.is_symlink():
        raise RecordError(f"{DECISION_LOG} is a symlink; refusing to append through it")
    if log.exists() and (not log.is_file() or (original is not None and os.path.samefile(log, original))):
        raise RecordError(f"{DECISION_LOG} is not a separate regular file")
    if log.resolve().parent != folder:
        raise RecordError(f"{DECISION_LOG} would land outside {folder}")
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    return os.fdopen(os.open(log, flags, 0o644), "a", encoding="utf-8")


def record_decision(log_dir: str | Path, packet_dict: dict, source: Source, decision: str,
                    by: str, note: str = "", now: datetime | None = None,
                    packet_name: str | None = None, packet_sha256: str | None = None) -> dict:
    """Append one decision line for a packet and return it.

    Before writing, the original is re-read and its hash compared with the one
    in the packet. If the original has changed since the packet was built, the
    decision is refused: Zach would be deciding about a text that no longer
    exists. Recording a decision never touches the original, whichever it is.

    ``packet_name`` and ``packet_sha256`` (the packet file's hash) name exactly
    which packet is decided, so history can tell two revisions with the same
    edition apart. Lines written before increment 2 lack them.
    """
    if decision not in DECISIONS:
        raise RecordError(f"decision must be one of {', '.join(DECISIONS)}")
    if not by.strip():
        raise RecordError("a decision needs a decider (by)")
    original = packet_dict["original"]
    current = sha256(source.read(original["name"]))
    if current != original["sha256"]:
        raise RecordError("the original has changed since this packet was built; rebuild the packet first")
    entry = {
        "at": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "decision": decision,
        "by": by,
        "original": original["name"],
        "original_sha256": original["sha256"],
        "edition": packet_dict["edition"]["name"],
        "edition_sha256": packet_dict["edition"]["sha256"],
        "checks_ok": packet_dict.get("ok"),
        "note": note,
    }
    if bool(packet_name) != bool(packet_sha256):
        # History needs both or neither (Copilot review on #9).
        raise RecordError("packet_name and packet_sha256 go together: give both or neither")
    if packet_sha256:
        entry["packet"] = packet_name
        entry["packet_sha256"] = packet_sha256
    folder = _outside_repo(Path(log_dir))
    folder.mkdir(parents=True, exist_ok=True)
    # Sources that live on disk can say where the original is, so the log can
    # be checked not to be the original under another name.
    original_path = source.path_of(original["name"]) if hasattr(source, "path_of") else None
    with _open_log(folder, original_path) as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry
