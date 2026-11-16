"""Draft a spec: list every difference so a person only has to label it.

Why this exists
---------------
Building a packet needs a ``spec.json`` that declares every change between
the original and the edition, and every quotation. Writing it by hand means
finding each difference by eye, which is exactly the reconstruction effort
the packet is meant to remove, and a missed difference only shows up as a
failed check afterwards.

``draft_spec`` does the finding. It walks the same word-by-word comparison the
builder's ``changes-labelled`` check uses and writes one change entry per
difference, with the texts filled in and the judgement left blank:

- ``kind`` is ``null`` and ``rationale`` is empty. Whether a change is an
  agent addition, a transformation or an interpretation, and why it was made,
  is a decision for the person (or agent) proposing the edition. The tool
  never guesses it, and ``build`` refuses the draft until every entry is
  labelled.
- Text between quotation marks in the edition is declared as a quotation.
  When the words appear in the original, its source is ``"original"``;
  otherwise the source is left blank, so ``build`` flags it until someone
  names where the words come from.

Each change's texts are widened, a character at a time, until they occur first
exactly where the difference is. The builder finds a declared text by its
first occurrence, so a bare ``the`` would otherwise point at the wrong place.
The widening steers clear of quotations where it can.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .build import QUOTE_RE, _covered, _differences, _find_span, _word_spans
from .record import RecordError, _outside_repo


# How far (in characters) the fine-grained search below may widen a snippet
# before falling back to whole words; keeps the search cheap on long texts.
_MAX_EXTRA = 120


def _first_at(text: str, start: int, end: int) -> bool:
    return text.find(text[start:end]) == start


def _overlaps_any(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(start < e and s < end for s, e in spans)


def _unique_snippet(text: str, span: tuple[int, int],
                    avoid: list[tuple[int, int]] = ()) -> tuple[int, int]:
    """The smallest widening of ``span`` whose text first occurs at ``span``.

    Widening goes a character at a time, so adjacent whitespace can do the
    job (`` calm`` rather than ``"calm" calm``). Snippets that would reach
    into an ``avoid`` span (a quotation) are passed over while a clean one
    exists: a change text that swallows an unchanged quotation would make an
    ``interpretation`` label fail ``no-interpretation-as-quotation`` although
    only words outside the quotation changed (Copilot on #11).
    """
    start, end = span
    if _first_at(text, start, end):
        return start, end
    fallback = None
    for extra in range(1, _MAX_EXTRA + 1):
        for left in range(extra + 1):
            s, e = start - left, end + (extra - left)
            if s < 0 or e > len(text) or not _first_at(text, s, e):
                continue
            if not _overlaps_any(s, e, avoid):
                return s, e
            fallback = fallback or (s, e)
    if fallback:
        return fallback
    # Long repeated text: widen by whole words, which always ends at a unique
    # snippet (at worst the whole text).
    words = _word_spans(text)
    after = [w for w in words if w[1] >= end]
    before = [w for w in reversed(words) if w[2] <= start]
    take_after = True
    while not _first_at(text, start, end):
        if (take_after and after) or not before:
            end = after.pop(0)[2]
        else:
            start = before.pop(0)[1]
        take_after = not take_after
    return start, end


def _runs(words: list[tuple[int, int]], quotes: list[tuple[int, int]]) -> list[list[tuple[int, int]]]:
    """Split changed words into runs at every quotation lying between two of
    them, so a change never spans an unchanged quotation (Codex on #11)."""
    runs: list[list[tuple[int, int]]] = []
    for word in words:
        if runs and not any(runs[-1][-1][1] <= qs and qe <= word[0] for qs, qe in quotes):
            runs[-1].append(word)
        else:
            runs.append([word])
    return runs


def draft_spec(original: str, edition: str) -> dict:
    """A spec skeleton for ``edition`` against ``original``: every difference
    as an unlabelled change, every quotation declared."""
    # Quotations first: a difference that only adds quotation marks around
    # the original's words is covered by declaring the quotation, exactly as
    # the builder treats it.
    quotations, quoted_edition, quoted_original = [], [], []
    seen = set()
    for match in QUOTE_RE.finditer(edition):
        words = match.group(1) if match.group(1) is not None else match.group(2)
        in_original = _find_span(original, words)
        if words not in seen:
            seen.add(words)
            quotations.append({"text": words, "source": "original" if in_original else "",
                               "speaker": None})
        if in_original:
            quoted_edition.append((match.start(), match.end()))
            quoted_original.append(in_original)

    all_quotes = [(m.start(), m.end()) for m in QUOTE_RE.finditer(edition)]
    changes = []
    for diff in _differences(original, edition):
        loose_ed = [w for w in diff["edition_words"] if not _covered(w, quoted_edition)]
        loose_orig = [w for w in diff["original_words"] if not _covered(w, quoted_original)]
        if not loose_ed and not loose_orig:
            continue  # only quotation marks were added; the quotation covers it
        # One change per run of changed words between quotations, paired in
        # order (``foo calm bar`` -> ``new "calm" other`` gives foo -> new and
        # bar -> other), so each can carry its own label.
        ed_runs, orig_runs = _runs(loose_ed, all_quotes), _runs(loose_orig, quoted_original)
        for index in range(max(len(ed_runs), len(orig_runs))):
            entry = {"id": f"c{len(changes) + 1}", "kind": None, "rationale": ""}
            if index < len(orig_runs):
                run = orig_runs[index]
                s, e = _unique_snippet(original, (run[0][0], run[-1][1]))
                entry["original_text"] = original[s:e]
            if index < len(ed_runs):
                run = ed_runs[index]
                s, e = _unique_snippet(edition, (run[0][0], run[-1][1]), all_quotes)
                entry["edition_text"] = edition[s:e]
            else:
                entry["edition_text"] = ""  # a pure deletion
            changes.append(entry)

    return {
        "_draft": ("Written by `draft-spec`. Give every change a kind (agent addition, "
                   "transformation or interpretation) and a rationale, and every quotation "
                   "a source, then run build. The tool never chooses labels."),
        "changes": changes,
        "quotations": quotations,
    }


def write_spec(spec: dict, out_path: Path) -> Path:
    """Write the draft into the content folder, never over an existing file
    and never inside this repository."""
    folder = _outside_repo(out_path.parent)
    path = folder / out_path.name
    folder.mkdir(parents=True, exist_ok=True)
    # lexists, not exists: a dangling symlink counts as taken. Mode "x" alone
    # is not enough: on Windows it follows a dangling link and creates the
    # target (CI on #11), so check the name itself first, as write_packet does.
    if os.path.lexists(path):
        raise RecordError(f"{path.name} already exists; choose another name")
    try:
        # Mode "x": create or fail; never follows a planted symlink.
        with open(path, "x", encoding="utf-8") as handle:
            handle.write(json.dumps(spec, ensure_ascii=False, indent=2) + "\n")
    except FileExistsError as error:
        raise RecordError(f"{path.name} already exists; choose another name") from error
    return path
