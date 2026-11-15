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
    folder = _outside_repo(Path(out_dir))
    folder.mkdir(parents=True, exist_ok=True)
    json_path, md_path = folder / f"{stem}.packet.json", folder / f"{stem}.packet.md"
    for path in (json_path, md_path):
        if path.exists():
            raise RecordError(f"{path.name} already exists; use a new stem")
    json_path.write_text(json.dumps(packet.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(packet), encoding="utf-8")
    return json_path, md_path


def record_decision(log_dir: str | Path, packet_dict: dict, source: Source, decision: str,
                    by: str, note: str = "", now: datetime | None = None) -> dict:
    """Append one decision line for a packet and return it.

    Before writing, the original is re-read and its hash compared with the one
    in the packet. If the original has changed since the packet was built, the
    decision is refused: Zach would be deciding about a text that no longer
    exists. Recording a decision never touches the original, whichever it is.
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
    folder = _outside_repo(Path(log_dir))
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / DECISION_LOG, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry
