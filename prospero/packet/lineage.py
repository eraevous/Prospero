"""Revisions and history: how packets for one original relate over time.

Increment 2 (HO-PRO-20261116-P8CB), scoped with Kate (API instance) on
2026-11-16. Two things live here:

1. **Revision lineage.** A revision is a *new* packet that names its parent
   packet by path and by the SHA-256 of the parent file's text. Building a
   revision never touches the parent or any decision already recorded; the
   parent is only read. A parent for a different original (or for the same
   name with different bytes) is refused.

2. **History.** ``history`` reads every packet for one original and the
   decision log, and reports the *recorded facts*: which packets exist, which
   revises which, and every decision in the order it was written. It
   deliberately does **not** derive a single state for the original ("accepted",
   "current edition"). Whether an accepted edition can be superseded, what two
   conflicting decisions mean, and whether branching is allowed are Zach's
   calls (Kate's advice, 2026-11-16), so two children of one parent are shown
   side by side and no winner is picked.

History fails closed: a corrupt packet or log line, a missing or changed
parent, a parent for another original, a cycle, or an original whose bytes no
longer match the packets is reported as a problem, never skipped quietly. The
command line exits 1 when there is any problem.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .build import sha256
from .sources import Source, SourceError


def _canonical(source: Source, name: str) -> str:
    """The name a record should use for ``name`` (Codex review on #9: an
    equivalent spelling such as ``./packets/x`` must link to the same packet).
    Sources without ``canonical`` keep names as given."""
    return source.canonical(name) if hasattr(source, "canonical") else name


def _packet_fields(data) -> tuple[dict, dict, dict | None]:
    """The original, edition and parent of a parsed packet, or ValueError if any
    has the wrong shape (Codex review on #9: valid JSON with ``"edition": null``
    must be reported as a corrupt packet, not crash history)."""
    if not isinstance(data, dict):
        raise ValueError("not a JSON object")
    original, edition, parent = data.get("original"), data.get("edition"), data.get("parent")
    for label, part in (("original", original), ("edition", edition)):
        if not isinstance(part, dict) or not isinstance(part.get("name"), str) \
                or not isinstance(part.get("sha256"), str):
            raise ValueError(f"{label} must be an object with a name and sha256")
    if parent is not None and not (isinstance(parent, dict) and isinstance(parent.get("name"), str)
                                   and isinstance(parent.get("sha256"), str)):
        raise ValueError("parent must be null or an object with a name and sha256")
    return original, edition, parent

PACKETS = "packets"
DECISION_LOG = "decisions.jsonl"


class LineageError(Exception):
    """A revision could not be linked to the parent it names."""


def parent_ref(source: Source, parent_name: str, original_name: str) -> dict:
    """Read a parent packet and return the reference a revision stores.

    The parent must be a packet for the same original, built from the same
    bytes as the original holds now. The reference is ``{"name", "sha256"}``,
    where ``sha256`` is the hash of the parent file's text, so a later edit to
    the parent breaks the link visibly instead of silently.
    """
    parent_name = _canonical(source, parent_name)
    text = source.read(parent_name)
    try:
        parent_original, _, _ = _packet_fields(json.loads(text))
    except (json.JSONDecodeError, ValueError) as error:
        raise LineageError(f"{parent_name} is not a packet: {error}") from error
    if parent_original.get("name") != original_name:
        raise LineageError(f"{parent_name} is a packet for {parent_original.get('name')!r}, not {original_name!r}")
    if parent_original.get("sha256") != sha256(source.read(original_name)):
        raise LineageError(f"the original has changed since {parent_name} was built; rebuild from the original")
    return {"name": parent_name, "sha256": sha256(text)}


@dataclass
class Node:
    """One packet as history sees it. ``sha256`` is the packet file's hash."""

    name: str
    sha256: str
    original_sha256: str
    edition: str
    edition_sha256: str
    checks_ok: bool | None
    parent: dict | None
    children: list[str] = field(default_factory=list)
    # The parent this packet was actually linked to, by canonical name (None
    # when it has no parent or the link is broken).
    linked_parent: str | None = None
    decisions: list[dict] = field(default_factory=list)


@dataclass
class History:
    original: str
    original_sha256: str
    packets: dict[str, Node]
    events: list[dict]
    problems: list[str]

    @property
    def ok(self) -> bool:
        return not self.problems

    def roots(self) -> list[str]:
        """Packets with no parent (or a parent that couldn't be linked), by name."""
        return sorted(n for n, node in self.packets.items() if node.linked_parent is None)

    def to_dict(self) -> dict:
        return {
            "original": {"name": self.original, "sha256": self.original_sha256},
            "packets": {name: {"sha256": n.sha256, "edition": n.edition, "edition_sha256": n.edition_sha256,
                               "checks_ok": n.checks_ok, "parent": n.parent, "children": n.children,
                               "decisions": n.decisions}
                        for name, n in sorted(self.packets.items())},
            "events": self.events,
            "problems": self.problems,
            "ok": self.ok,
        }


def _read_packets(source: Source, original: str, problems: list[str]) -> dict[str, Node]:
    nodes = {}
    for listed in source.names(PACKETS, "*.packet.json"):
        # Key every packet by the same canonical name parent references use
        # (Codex review on #9: with packets/ a symlink inside the content
        # folder, the listed and canonical spellings differ).
        try:
            name = _canonical(source, listed)
        except SourceError as error:
            problems.append(f"{listed}: unreadable packet ({error})")
            continue
        if name in nodes:
            continue  # the same file reached by two spellings
        try:
            text = source.read(name)
            data = json.loads(text)
            data_original, edition, parent = _packet_fields(data)
        except (SourceError, json.JSONDecodeError, ValueError) as error:
            # Report it: a corrupt packet might belong to this original, and
            # dropping it would make the history look complete when it isn't.
            problems.append(f"{name}: unreadable packet ({error})")
            continue
        if data_original["name"] != original:
            continue
        nodes[name] = Node(name=name, sha256=sha256(text), original_sha256=data_original["sha256"],
                           edition=edition["name"], edition_sha256=edition["sha256"],
                           checks_ok=data.get("ok"), parent=parent)
    return nodes


def _check_links(source: Source, nodes: dict[str, Node], current: str, problems: list[str]) -> None:
    for name, node in sorted(nodes.items()):
        if node.original_sha256 != current:
            problems.append(f"{name}: built from different bytes of the original than it holds now")
        if node.parent is None:
            continue
        parent_name, parent_hash = node.parent["name"], node.parent["sha256"]
        try:
            parent_name = _canonical(source, parent_name)
        except SourceError:
            problems.append(f"{name}: parent {parent_name} is missing")
            continue
        parent = nodes.get(parent_name)
        if parent is None:
            problems.append(f"{name}: parent {parent_name} is a packet for another original, or unreadable")
            continue
        if parent.sha256 != parent_hash:
            problems.append(f"{name}: parent {parent_name} has changed since this revision was built")
        if parent.original_sha256 != node.original_sha256:
            problems.append(f"{name}: parent {parent_name} was built from different bytes of the original")
        parent.children.append(name)
        node.linked_parent = parent_name
    for node in nodes.values():
        node.children.sort()
    # Content hashes make a true cycle practically impossible, but a parent
    # field is only data in a file, so check rather than assume.
    for name in sorted(nodes):
        seen, cursor = set(), name
        while cursor in nodes and nodes[cursor].parent:
            if cursor in seen:
                problems.append(f"{name}: its ancestry loops back on itself")
                break
            seen.add(cursor)
            try:
                cursor = _canonical(source, nodes[cursor].parent["name"])
            except SourceError:
                break


def _read_decisions(source: Source, original: str, nodes: dict[str, Node], problems: list[str]) -> list[dict]:
    try:
        text = source.read(DECISION_LOG)
    except SourceError:
        return []  # no decisions recorded yet
    events = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            entry_original = entry["original"]
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            problems.append(f"{DECISION_LOG} line {number}: unreadable ({error})")
            continue
        if entry_original != original:
            continue
        if entry.get("packet_sha256"):
            # Decisions recorded since increment 2 name the packet exactly.
            matched = [n for n in nodes.values() if n.sha256 == entry["packet_sha256"]]
            if not matched:
                problems.append(f"{DECISION_LOG} line {number}: decides a packet that isn't here "
                                f"({entry.get('packet', '?')}) or has changed since")
        else:
            # Older lines name only the original and edition; every packet with
            # that pair is a candidate, and history says so rather than guess.
            matched = [n for n in nodes.values()
                       if n.edition_sha256 == entry.get("edition_sha256")
                       and n.original_sha256 == entry.get("original_sha256")]
            if not matched:
                # Codex review on #9: a missing packet is a problem for older
                # lines too, or history looks complete when it isn't.
                problems.append(f"{DECISION_LOG} line {number}: decides edition {entry.get('edition', '?')}, "
                                f"but no packet here has that original and edition")
        event = {"line": number, "at": entry.get("at"), "decision": entry.get("decision"), "by": entry.get("by"),
                 "note": entry.get("note", ""), "packets": sorted(n.name for n in matched)}
        if not entry.get("packet_sha256") and len(matched) > 1:
            event["ambiguous"] = True
        events.append(event)
        for node in matched:
            node.decisions.append({k: event[k] for k in ("line", "at", "decision", "by")})
    return events


def history(source: Source, original: str) -> History:
    """Everything recorded about one original: packets, lineage, decisions.

    Raises ``SourceError`` if the original itself can't be read.
    """
    problems: list[str] = []
    current = sha256(source.read(original))
    nodes = _read_packets(source, original, problems)
    _check_links(source, nodes, current, problems)
    events = _read_decisions(source, original, nodes, problems)
    return History(original=original, original_sha256=current, packets=nodes, events=events, problems=problems)


def render_history(h: History) -> str:
    """A plain-text view: the revision tree, then the decisions in order."""
    lines = [f"History of {h.original} (sha256 {h.original_sha256[:12]}…)", ""]
    if not h.packets:
        lines.append("No packets for this original.")

    def walk(name: str, depth: int, seen: set) -> None:
        node = h.packets[name]
        calls = ", ".join(f"{d['decision']} by {d['by']}" for d in node.decisions) or "no decision recorded"
        checks = {True: "checks ok", False: "checks FAILED"}.get(node.checks_ok, "checks unknown")
        lines.append(f"{'  ' * depth}- {name} (edition {node.edition}; {checks}; {calls})")
        if name in seen:
            return
        for child in node.children:
            walk(child, depth + 1, seen | {name})

    for root in h.roots():
        walk(root, 0, set())
    lines += ["", "Decisions, in the order recorded:"]
    for e in h.events:
        which = ", ".join(e["packets"]) or "no matching packet"
        flag = " (ambiguous: older line names no packet)" if e.get("ambiguous") else ""
        lines.append(f"- line {e['line']}: {e['at']} {e['decision']} by {e['by']} on {which}{flag}"
                     + (f": {e['note']}" if e["note"] else ""))
    if not h.events:
        lines.append("- none")
    if h.problems:
        lines += ["", "Problems (history may be incomplete):"] + [f"- {p}" for p in h.problems]
    return "\n".join(lines) + "\n"
