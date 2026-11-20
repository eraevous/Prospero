"""Build and check an editorial packet.

An *editorial packet* puts an original text beside a proposed alternate edition
so Zach can accept, reject or revise the edition without losing the original.
It is the first increment proposed in the Prospero kickoff (handoff
HO-PRO-20261109-CDAD). This module holds the mechanics only; it never chooses
a passage or writes an edition itself.

Inputs
------
- the **original**, read through a source (see ``sources.py``);
- the **edition**, read through a source;
- a **spec** (a plain dict, usually loaded from JSON) that declares:

  ``changes``: every place the edition differs from the original, each with
    ``id``, ``kind`` (one of ``KINDS``), ``rationale``, ``edition_text`` (the
    passage as it reads in the edition; empty for a pure deletion) and
    ``original_text`` (what it replaced or cut; leave it out only for pure
    additions, since every original word that changed must be named).

  ``quotations``: every quoted passage in the edition (text between double
    quotation marks), each with ``text``, ``source`` (``"original"`` or the
    name of another text in the same source) and, optionally, ``speaker``.

Checks (the kickoff's acceptance checks, as code)
-------------------------------------------------
1. ``original-unchanged``: the original's hash is recorded and re-verified.
2. ``quotations-resolve``: every quoted passage in the edition is declared and
   appears word for word in its named source.
3. ``changes-labelled``: every change has an allowed kind and a rationale, and
   every difference between original and edition is covered by a declared change.
4. ``no-interpretation-as-quotation``: no passage labelled ``interpretation``
   sits inside quotation marks, where a reader would take it for someone's words.

A packet is built even when checks fail, so Zach (or the agent preparing it) can
see exactly what is wrong. ``Packet.ok`` says whether every check passed.
"""

from __future__ import annotations

import difflib
import hashlib
import re
from dataclasses import dataclass, field

from .sources import Source, SourceError

# The three labels the kickoff asks for. "agent addition": new material the
# agent wrote. "transformation": the original's content, reworded or moved.
# "interpretation": the agent's reading of what the original means.
KINDS = ("agent addition", "transformation", "interpretation")

# The format every packet names in its "format" field. Readers (review.py)
# refuse anything else, so the writer and the readers share this one name.
PACKET_FORMAT = "prospero.editorial-packet.v0"

# Text between straight or curly double quotation marks. Single quotes are left
# alone because apostrophes make them ambiguous in ordinary prose. A quotation
# may run across line breaks, as quotations in prose often do.
QUOTE_RE = re.compile(r'"([^"]+)"|“([^”]+)”')


def sha256(text: str) -> str:
    """SHA-256 of the text's UTF-8 bytes, as hex."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def line_of(text: str, offset: int) -> int:
    """1-based line number of a character offset, for human-readable locators."""
    return text.count("\n", 0, offset) + 1


@dataclass
class Check:
    name: str
    ok: bool
    problems: list[str] = field(default_factory=list)


@dataclass
class Packet:
    original_name: str
    original: str
    original_sha256: str
    edition_name: str
    edition: str
    edition_sha256: str
    changes: list[dict]
    quotations: list[dict]
    checks: list[Check]
    # A revision names its parent packet: {"name", "sha256"} (see lineage.py).
    parent: dict | None = None
    # Every word the changes-labelled check found unlabelled, as [start, end]
    # character offsets on each side. Recorded so a view (review.py) shows
    # exactly what the check found instead of re-deriving it.
    unlabelled: dict | None = None

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def to_dict(self) -> dict:
        return {
            "format": PACKET_FORMAT,
            "original": {"name": self.original_name, "sha256": self.original_sha256, "text": self.original},
            "edition": {"name": self.edition_name, "sha256": self.edition_sha256, "text": self.edition},
            "changes": self.changes,
            "quotations": self.quotations,
            "checks": [{"name": c.name, "ok": c.ok, "problems": c.problems} for c in self.checks],
            "ok": self.ok,
            "parent": self.parent,
            "unlabelled": self.unlabelled,
        }


def _find_span(haystack: str, needle: str) -> tuple[int, int] | None:
    """First occurrence of ``needle`` as (start, end) offsets, or None."""
    if not needle:
        return None
    start = haystack.find(needle)
    return None if start < 0 else (start, start + len(needle))


def _covered(span: tuple[int, int], labelled: list[tuple[int, int]]) -> bool:
    """True when every character of ``span`` lies inside the labelled spans.

    Full coverage, not mere overlap: a label naming one letter of a word must
    not vouch for the rest of that word.
    """
    position = span[0]
    for start, end in sorted(labelled):
        if start <= position < end:
            position = end
        if position >= span[1]:
            return True
    return False


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _word_spans(text: str) -> list[tuple[str, int, int]]:
    """Each run of non-space characters with its offsets. Diffing words rather
    than characters keeps the reported differences readable and stops a changed
    space from counting as an edit."""
    return [(m.group(), m.start(), m.end()) for m in re.finditer(r"\S+", text)]


def _differences(original: str, edition: str) -> list[dict]:
    """Where the edition departs from the original, word by word.

    Each entry has the original span, the edition span (character offsets) and
    the changed words on each side one by one. An insertion has no original span;
    a deletion no edition span.
    """
    a, b = _word_spans(original), _word_spans(edition)
    matcher = difflib.SequenceMatcher(None, [w for w, _, _ in a], [w for w, _, _ in b], autojunk=False)
    found = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        orig_span = (a[i1][1], a[i2 - 1][2]) if i1 < i2 else None
        ed_span = (b[j1][1], b[j2 - 1][2]) if j1 < j2 else None
        found.append({"original": orig_span, "edition": ed_span,
                      "original_words": [(start, end) for _, start, end in a[i1:i2]],
                      "edition_words": [(start, end) for _, start, end in b[j1:j2]]})
    return found


class SpecError(ValueError):
    """The spec is not shaped as ``build_packet`` expects (security pass,
    2026-11-19). A spec is hand-edited JSON, so a wrong shape is an ordinary
    mistake: it gets one plain message, not a Python traceback."""


# Which fields each spec entry may carry, and the only types they may have.
# ``None`` (JSON null) is allowed wherever the builder already reads a missing
# field as empty; ``draft-spec`` writes ``"kind": null`` for a person to fill.
_TEXT = (str, type(None))
_CHANGE_FIELDS = {"id": (str, int, type(None)), "kind": _TEXT, "rationale": _TEXT,
                  "edition_text": _TEXT, "original_text": _TEXT}
_QUOTATION_FIELDS = {"text": (str,), "source": _TEXT, "speaker": _TEXT}


def _type_name(value: object) -> str:
    """The JSON name for a value's type, for messages."""
    if isinstance(value, bool):
        return "true/false"
    return {dict: "an object", list: "a list", str: "a string", int: "a number",
            float: "a number", type(None): "null"}.get(type(value), type(value).__name__)


def check_spec_shape(spec: object) -> None:
    """Raise ``SpecError`` unless ``spec`` is an object whose ``changes`` and
    ``quotations`` (each optional) are lists of objects with fields of the
    right types. Messages name the field and the type found, never the value:
    the spec quotes the person's writing, and errors end up in terminals and
    logs (the 2026-11-18 content-leak audit). Unknown fields are left alone,
    as before (``draft-spec`` writes ``_draft``)."""
    if not isinstance(spec, dict):
        raise SpecError(f"the spec must be a JSON object, not {_type_name(spec)}")
    for key, fields in (("changes", _CHANGE_FIELDS), ("quotations", _QUOTATION_FIELDS)):
        entries = spec.get(key, [])
        if not isinstance(entries, list):
            raise SpecError(f"spec {key!r} must be a list, not {_type_name(entries)}")
        for index, entry in enumerate(entries, start=1):
            if not isinstance(entry, dict):
                raise SpecError(f"spec {key!r} entry {index} must be an object, not {_type_name(entry)}")
            for field_name, allowed in fields.items():
                if field_name in entry and (not isinstance(entry[field_name], allowed)
                                            or isinstance(entry[field_name], bool)):
                    raise SpecError(f"spec {key!r} entry {index}: {field_name!r} must be text"
                                    f"{' or a number' if int in allowed else ''}"
                                    f"{' or null' if type(None) in allowed else ''}, "
                                    f"not {_type_name(entry[field_name])}")


def build_packet(source: Source, original_name: str, edition_name: str, spec: dict,
                 edition_source: Source | None = None, parent: dict | None = None) -> Packet:
    """Read both texts, resolve the spec against them and run every check.

    ``edition_source`` defaults to ``source``; pass another when the edition is
    kept apart from the originals. ``parent`` is the reference returned by
    ``lineage.parent_ref`` when this packet revises an earlier one; it is only
    stored, never used to change the parent.
    """
    check_spec_shape(spec)
    edition_source = edition_source or source
    original = source.read(original_name)
    original_hash = sha256(original)
    edition = edition_source.read(edition_name)

    # --- changes: locate each declared change and check its label -----------
    changes, label_problems, change_spans = [], [], []
    for index, raw in enumerate(spec.get("changes", [])):
        cid = str(raw.get("id") or f"change-{index + 1}")
        kind, rationale = raw.get("kind"), (raw.get("rationale") or "").strip()
        ed_text, orig_text = raw.get("edition_text") or "", raw.get("original_text") or ""
        if kind not in KINDS:
            label_problems.append(f"{cid}: kind {kind!r} is not one of {', '.join(KINDS)}")
        if not rationale:
            label_problems.append(f"{cid}: no rationale")
        ed_span = _find_span(edition, ed_text)
        orig_span = _find_span(original, orig_text)
        if ed_text and ed_span is None:
            label_problems.append(f"{cid}: edition_text not found in the edition")
        if orig_text and orig_span is None:
            label_problems.append(f"{cid}: original_text not found in the original")
        if not ed_text and not orig_text:
            label_problems.append(f"{cid}: names neither edition_text nor original_text")
        change_spans.append((cid, kind, ed_span, orig_span))
        changes.append({
            "id": cid, "kind": kind, "rationale": rationale,
            "edition_text": ed_text, "original_text": orig_text,
            "edition_line": line_of(edition, ed_span[0]) if ed_span else None,
            "original_line": line_of(original, orig_span[0]) if orig_span else None,
        })

    # Declared quotations that actually appear in the edition count as
    # labelled: putting the original's words in quotation marks is itself a
    # change, and the quotations check below makes sure the words inside are
    # verbatim. A declaration with no quotation in the edition exempts nothing,
    # so a stale entry can't hide a deletion.
    declared_texts = {raw.get("text", "") for raw in spec.get("quotations", [])}
    present = [(m.start(), m.end(), m.group(1) or m.group(2)) for m in QUOTE_RE.finditer(edition)]
    quoted_spans = [(start, end) for start, end, text in present if text in declared_texts]
    present_texts = {text for _, _, text in present if text in declared_texts}

    # Where those quotations sit in the original, so the quotation marks added
    # around them don't count as unlabelled edits on the original side.
    quoted_in_original = [span for raw in spec.get("quotations", [])
                          if (raw.get("source") or "original") == "original"
                          and raw.get("text", "") in present_texts
                          for span in [_find_span(original, raw.get("text", ""))] if span]

    # Every difference must fall under some declared change, word by word and
    # on both sides. Word by word, so a labelled addition can't vouch for an
    # unlabelled cut that difflib happens to merge with it; both sides, so a
    # deletion is caught even when it is folded into a replacement.
    labelled_edition = [s for _, _, s, _ in change_spans if s] + quoted_spans
    labelled_original = [s for _, _, _, s in change_spans if s] + quoted_in_original
    unlabelled = {"edition": [], "original": []}
    for diff in _differences(original, edition):
        loose = [w for w in diff["edition_words"] if not _covered(w, labelled_edition)]
        unlabelled["edition"].extend([start, end] for start, end in loose)
        if loose:
            label_problems.append(f"unlabelled change at edition line {line_of(edition, loose[0][0])}: "
                                  f"{edition[loose[0][0]:loose[-1][1]]!r}")
        cut = [w for w in diff["original_words"] if not _covered(w, labelled_original)]
        unlabelled["original"].extend([start, end] for start, end in cut)
        if cut:
            label_problems.append(f"unlabelled change to original line {line_of(original, cut[0][0])}: "
                                  f"{original[cut[0][0]:cut[-1][1]]!r} (name it as original_text)")

    # --- quotations: every quoted passage must be declared and resolve --------
    declared = {}
    for raw in spec.get("quotations", []):
        declared.setdefault(raw.get("text", ""), raw)
    quotations, quote_problems, quote_spans = [], [], []
    for match in QUOTE_RE.finditer(edition):
        text = match.group(1) or match.group(2)
        quote_spans.append((match.start(), match.end(), text))
        entry = declared.get(text)
        if entry is None:
            quote_problems.append(f"quotation on edition line {line_of(edition, match.start())} is not declared: {text!r}")
            continue
        source_name = entry.get("source") or "original"
        try:
            haystack = original if source_name == "original" else source.read(source_name)
        except SourceError as error:
            quote_problems.append(f"{text!r}: {error}")
            continue
        span = _find_span(haystack, text)
        if span is None:
            quote_problems.append(f"{text!r} does not appear word for word in {source_name!r}")
            continue
        quotations.append({
            "text": text,
            "speaker": entry.get("speaker"),
            "locator": {
                "source": source.name,
                "name": original_name if source_name == "original" else source_name,
                "sha256": sha256(haystack),
                "offset": span[0],
                "line": line_of(haystack, span[0]),
            },
            "edition_line": line_of(edition, match.start()),
        })

    # --- an interpretation must never sit inside quotation marks --------------
    interp_problems = []
    for cid, kind, ed_span, _ in change_spans:
        if kind != "interpretation" or ed_span is None:
            continue
        for start, end, text in quote_spans:
            if _overlaps(ed_span, (start, end)):
                interp_problems.append(f"{cid}: interpretation appears inside quotation marks: {text!r}")

    # --- the original is re-read and must be byte-for-byte what we started with
    reread_hash = sha256(source.read(original_name))
    unchanged = Check("original-unchanged", reread_hash == original_hash,
                      [] if reread_hash == original_hash else ["original changed while the packet was built"])

    return Packet(
        original_name=original_name, original=original, original_sha256=original_hash,
        edition_name=edition_name, edition=edition, edition_sha256=sha256(edition),
        changes=changes, quotations=quotations,
        checks=[
            unchanged,
            Check("quotations-resolve", not quote_problems, quote_problems),
            Check("changes-labelled", not label_problems, label_problems),
            Check("no-interpretation-as-quotation", not interp_problems, interp_problems),
        ],
        parent=parent,
        unlabelled=unlabelled,
    )
