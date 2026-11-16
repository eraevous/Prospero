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

Each change's texts are widened, a word at a time, until they occur first
exactly where the difference is. The builder finds a declared text by its
first occurrence, so a bare ``the`` would otherwise point at the wrong place.
"""

from __future__ import annotations

import json
from pathlib import Path

from .build import QUOTE_RE, _covered, _differences, _find_span, _word_spans
from .record import RecordError, _outside_repo


def _unique_snippet(text: str, span: tuple[int, int]) -> tuple[int, int]:
    """Widen ``span`` by whole words until its text first occurs at ``span``.

    Words are added after, then before, in turn. In the worst case the span
    grows to the whole text, whose first occurrence is always itself.
    """
    words = _word_spans(text)
    start, end = span
    after = [w for w in words if w[1] >= end]
    before = [w for w in reversed(words) if w[2] <= start]
    take_after = True
    while _find_span(text, text[start:end])[0] != start:
        if (take_after and after) or not before:
            end = after.pop(0)[2]
        else:
            start = before.pop(0)[1]
        take_after = not take_after
    return start, end


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

    changes = []
    for diff in _differences(original, edition):
        loose_ed = [w for w in diff["edition_words"] if not _covered(w, quoted_edition)]
        loose_orig = [w for w in diff["original_words"] if not _covered(w, quoted_original)]
        if not loose_ed and not loose_orig:
            continue  # only quotation marks were added; the quotation covers it
        entry = {"id": f"c{len(changes) + 1}", "kind": None, "rationale": ""}
        if loose_orig:
            s, e = _unique_snippet(original, (loose_orig[0][0], loose_orig[-1][1]))
            entry["original_text"] = original[s:e]
        if loose_ed:
            s, e = _unique_snippet(edition, (loose_ed[0][0], loose_ed[-1][1]))
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
    try:
        # Mode "x": create or fail; never follows a planted symlink.
        with open(path, "x", encoding="utf-8") as handle:
            handle.write(json.dumps(spec, ensure_ascii=False, indent=2) + "\n")
    except FileExistsError as error:
        raise RecordError(f"{path.name} already exists; choose another name") from error
    return path
