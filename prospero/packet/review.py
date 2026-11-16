"""Review sheet: one self-contained HTML page for deciding on a packet.

Why this exists
---------------
The kickoff's usefulness check for editorial packets is "a concrete editorial
decision with less reconstruction effort". The packet's Markdown view prints the
original, then the edition, then a list of changes, so the reader still has to
find each change in two texts by eye. The review sheet does that work: the
original and the edition sit side by side, every declared change is
highlighted in both and coloured by its label (agent addition, transformation,
interpretation), quotations are underlined with their source locator, and any
difference *nobody declared* is marked as unlabelled.

What it does not do
-------------------
It decides nothing and records nothing. It reads a packet that ``build``
already wrote and renders what is in it. The decision is still made with
``decide``; the sheet only prints the commands for it. It shows whether the
original on disk still matches the packet's hash, because a sheet for a text
that has since changed would mislead.

The page has no scripts and loads nothing from the network: plain HTML and
CSS, so it opens offline and can be kept beside the packet. Clicking a change
in the list jumps to it in both texts (CSS ``:target``, no JavaScript).

Every piece of text from the packet is HTML-escaped before it is written.
"""

from __future__ import annotations

import html
import json
import os
import shlex
import tempfile
from pathlib import Path

# _covered is the builder's own coverage test (the union of labelled spans),
# so a word the checks accept is never marked unlabelled here (Codex on #10).
from .build import KINDS, QUOTE_RE, _covered, _differences, _find_span, sha256
from .record import RecordError, _outside_repo
from .sources import Source, SourceError

FORMAT = "prospero.editorial-packet.v0"

# The first line of every sheet. write_review only replaces a file that starts
# with it, so it can never overwrite a text that happens to have the sheet's
# name (an original or edition called first.review.html, say).
MARKER = "<!doctype html><!-- prospero review sheet -->"

# One CSS class per label. Unknown labels (a failed check) get "unknown".
KIND_CLASS = {"agent addition": "add", "transformation": "xf", "interpretation": "interp"}


def _segments(text: str, marks: list[tuple[int, int, str, str | None]]) -> str:
    """Render ``text`` as HTML with marked spans.

    ``marks`` holds (start, end, css_class, anchor_id). Marks may overlap: the
    text is cut at every mark boundary and each piece carries the classes of
    every mark covering it, so nothing has to nest. Each anchor id appears
    once (ids must be unique in a page): on the first piece of its mark, or,
    when another mark's id already sits there (two changes with the same
    span), on an empty marker just before it, so every change's link has a
    target (Codex on #10).
    """
    cuts = sorted({0, len(text)} | {p for s, e, _, _ in marks for p in (s, e)})
    # Sweep: marks open and close at cut points, so the marks covering a piece
    # are kept as a running set instead of rescanning every mark per piece
    # (Copilot on #10: thousands of unlabelled words made that quadratic).
    opening: dict[int, list[int]] = {}
    closing: dict[int, list[int]] = {}
    for index, (s, e, _, _) in enumerate(marks):
        if s < e:
            opening.setdefault(s, []).append(index)
            closing.setdefault(e, []).append(index)
    active: set[int] = set()
    placed: set[str] = set()
    out = []
    for start, end in zip(cuts, cuts[1:]):
        active.difference_update(closing.get(start, ()))
        active.update(opening.get(start, ()))
        piece = html.escape(text[start:end])
        covering = [marks[i] for i in sorted(active)]
        if not covering:
            out.append(piece)
            continue
        classes = " ".join(sorted({token for m in covering for token in m[2].split()}))
        pending = list(dict.fromkeys(m[3] for m in covering if m[3] and m[3] not in placed))
        placed.update(pending)
        # The first pending id goes on the piece, any others on empty markers.
        out.extend(f'<span id="{html.escape(a, quote=True)}"></span>' for a in pending[1:])
        attrs = f' class="{classes}"'
        if pending:
            attrs += f' id="{html.escape(pending[0], quote=True)}"'
        titles = [m[3] for m in covering if m[3]]
        if titles:
            attrs += f' title="{html.escape(", ".join(t.split(":", 1)[-1] for t in titles), quote=True)}"'
        out.append(f"<span{attrs}>{piece}</span>")
    return "".join(out)


def _marks(packet: dict) -> tuple[list, list]:
    """Highlight marks for the original and the edition.

    Changes are located the way ``build`` locates them (first occurrence of
    the declared text), so the sheet highlights exactly what the checks
    looked at. Words that differ between the texts but sit under no declared
    change or quotation are marked ``loose``: that is what the
    ``changes-labelled`` check complains about, shown in place.
    """
    original, edition = packet["original"]["text"], packet["edition"]["text"]
    orig_marks, ed_marks = [], []
    for change in packet.get("changes", []):
        css = "chg " + KIND_CLASS.get(change.get("kind"), "unknown")
        cid = str(change.get("id", ""))
        for text_value, target, marks, side in ((change.get("original_text"), original, orig_marks, "o"),
                                                (change.get("edition_text"), edition, ed_marks, "e")):
            span = _find_span(target, text_value or "")
            if span:
                marks.append((span[0], span[1], css, f"{side}:{cid}"))
    # Quotations: underline every declared passage where it actually sits
    # between quotation marks in the edition (found the way the builder finds
    # them, with QUOTE_RE, not by searching for the words, which could hit an
    # unquoted earlier copy; Codex on #10), and the place in the original its
    # locator names.
    # The packet keeps only quotations that resolved. One that was declared
    # but failed to resolve still counts as declared for changes-labelled, so
    # it must not be marked unlabelled (Copilot on #10). The builder names an
    # undeclared quotation in a quotations-resolve problem; every other quoted
    # passage was declared.
    resolved = {quote["text"] for quote in packet.get("quotations", [])}
    problems = [p for c in packet.get("checks", []) if c.get("name") == "quotations-resolve"
                for p in c.get("problems", [])]
    declared = set()
    for match in QUOTE_RE.finditer(edition):
        group = 1 if match.group(1) is not None else 2
        words = match.group(group)
        if words in resolved:
            declared.add(words)
            ed_marks.append((match.start(group), match.end(group), "quote", None))
        elif not any(p.endswith(f"is not declared: {words!r}") for p in problems):
            declared.add(words)  # declared, but it did not resolve: show that
            ed_marks.append((match.start(group), match.end(group), "quote badquote", None))
    for quote in packet.get("quotations", []):
        locator = quote.get("locator", {})
        if locator.get("name") == packet["original"]["name"]:
            start = locator.get("offset")
            if isinstance(start, int) and original[start:start + len(quote["text"])] == quote["text"]:
                orig_marks.append((start, start + len(quote["text"]), "quote", None))
    # Unlabelled differences, word by word, on both sides.
    # Only *declared* quotations exempt their words, as in build_packet: an
    # undeclared quotation is an unlabelled change and must show (Codex on #10).
    ed_known = [(s, e) for s, e, *_ in ed_marks] + [
        (m.start(), m.end()) for m in QUOTE_RE.finditer(edition)
        if (m.group(1) if m.group(1) is not None else m.group(2)) in declared]
    orig_known = [(s, e) for s, e, *_ in orig_marks]
    for diff in _differences(original, edition):
        for word in diff["edition_words"]:
            if not _covered(word, ed_known):
                ed_marks.append((word[0], word[1], "loose", None))
        for word in diff["original_words"]:
            if not _covered(word, orig_known):
                orig_marks.append((word[0], word[1], "loose", None))
    return orig_marks, ed_marks


def original_status(packet: dict, source: Source | None) -> tuple[bool | None, str]:
    """Does the original on disk still match the packet? (None: not checked.)"""
    if source is None:
        return None, "original on disk not checked"
    try:
        current = sha256(source.read(packet["original"]["name"]))
    except (SourceError, OSError, UnicodeDecodeError) as error:
        # Not only SourceError: an unreadable or non-UTF-8 original must show
        # as a failed status on the sheet, not crash it (Copilot on #10).
        return False, f"original could not be read: {error}"
    if current != packet["original"]["sha256"]:
        return False, "the original has changed since this packet was built; rebuild it before deciding"
    return True, "original on disk matches the packet"


def render_review(packet: dict, packet_name: str = "PACKET.json", source: Source | None = None) -> str:
    """The review sheet for one packet (a dict as written by ``write_packet``)."""
    if not isinstance(packet, dict) or packet.get("format") != FORMAT:
        found = packet.get("format") if isinstance(packet, dict) else type(packet).__name__
        raise RecordError(f"not an editorial packet (format {found!r})")
    esc = html.escape
    orig_marks, ed_marks = _marks(packet)
    loose = sum(1 for m in orig_marks + ed_marks if m[2] == "loose")
    on_disk_ok, on_disk = original_status(packet, source)

    checks = "".join(
        f'<li class="{"ok" if c.get("ok") else "fail"}">{"✓" if c.get("ok") else "✗"} {esc(str(c.get("name")))}'
        + ("<ul>" + "".join(f"<li>{esc(str(p))}</li>" for p in c.get("problems", [])) + "</ul>"
           if c.get("problems") else "") + "</li>"
        for c in packet.get("checks", []))
    verdict = "All checks passed" if packet.get("ok") else "Checks FAILED"

    cards = []
    for change in packet.get("changes", []):
        cid = esc(str(change.get("id", "")), quote=True)
        kind = change.get("kind")
        css = KIND_CLASS.get(kind, "unknown")
        rows = ""
        if change.get("original_text"):
            rows += f'<div class="was"><a href="#o:{cid}">was</a> {esc(change["original_text"])}</div>'
        if change.get("edition_text"):
            rows += f'<div class="now"><a href="#e:{cid}">now</a> {esc(change["edition_text"])}</div>'
        cards.append(f'<li class="card {css}"><span class="chip {css}">{esc(str(kind))}</span> '
                     f'<b>{cid}</b> {esc(change.get("rationale", ""))}{rows}</li>')

    quotes = "".join(
        f'<li>“{esc(q["text"])}”'
        f'{" (" + esc(q["speaker"]) + ")" if q.get("speaker") else ""}'
        f' — {esc(str(q["locator"].get("name")))} line {esc(str(q["locator"].get("line")))}</li>'
        for q in packet.get("quotations", []))

    parent = packet.get("parent")
    lineage = (f'<p class="meta">Revises <code>{esc(str(parent.get("name")))}</code> '
               f'(sha256 {esc(str(parent.get("sha256", ""))[:12])}…)</p>' if parent else "")
    legend = "".join(f'<span class="chip {KIND_CLASS[k]}">{k}</span>' for k in KINDS)
    pq = esc(packet_name, quote=True)
    # Shell-quote the name first, then HTML-escape the whole command: a name
    # with a space or a shell metacharacter must still copy as one argument
    # (Codex on #10). POSIX shell quoting.
    shell_name = shlex.quote(packet_name)
    commands = "\n".join(esc(f"python3 -m prospero.packet decide {shell_name} {d} --by NAME --note '…'")
                         for d in ("accept", "reject", "revise"))
    disk_class = {True: "ok", False: "fail", None: "meta"}[on_disk_ok]

    return f"""{MARKER}
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Review: {esc(packet["edition"]["name"])}</title>
<style>
:root {{ --bg:#fbfaf7; --fg:#1f1d1a; --muted:#6b665e; --line:#e2ddd3; --card:#fff;
  --add:#d9efdc; --add-b:#2e7d3c; --xf:#dbe7f7; --xf-b:#2f5f9e; --interp:#f6e3c6; --interp-b:#a5641a;
  --loose:#f7d4d4; --loose-b:#b3261e; --ok:#2e7d3c; --fail:#b3261e; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#171614; --fg:#ece8e1; --muted:#a39d93; --line:#34312c;
  --card:#201e1b; --add:#1f3a24; --add-b:#7cc58a; --xf:#1d2c44; --xf-b:#86aee6; --interp:#3e2c14; --interp-b:#e3a85e;
  --loose:#4a1f1d; --loose-b:#f08b84; --ok:#7cc58a; --fail:#f08b84; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; padding:24px 16px 48px; background:var(--bg); color:var(--fg);
  font:16px/1.55 Georgia, "Iowan Old Style", serif; }}
main {{ max-width:1180px; margin:0 auto; }}
h1 {{ font-size:1.5rem; margin:0 0 4px; }} h2 {{ font-size:1.05rem; margin:28px 0 8px;
  font-family:system-ui, sans-serif; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); }}
.meta {{ color:var(--muted); font:14px/1.4 system-ui, sans-serif; margin:2px 0; }}
.banner {{ border:1px solid var(--line); background:var(--card); border-radius:10px; padding:12px 16px;
  font:14px/1.5 system-ui, sans-serif; margin-top:16px; }}
.banner ul {{ margin:4px 0; padding-left:20px; }} .ok {{ color:var(--ok); }} .fail {{ color:var(--fail); }}
.banner li li {{ color:var(--fg); }}
.texts {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
@media (max-width:760px) {{ .texts {{ grid-template-columns:1fr; }} }}
.text {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }}
.text h2 {{ margin-top:0; }}
.text pre {{ white-space:pre-wrap; word-wrap:break-word; font:inherit; margin:0; }}
.chg {{ border-radius:3px; padding:0 1px; scroll-margin-top:40vh; }}
.add {{ background:var(--add); }} .xf {{ background:var(--xf); }} .interp {{ background:var(--interp); }}
.unknown {{ outline:1px dashed var(--fail); }}
.quote {{ text-decoration:underline dotted; text-underline-offset:3px; }}
.badquote {{ text-decoration:underline wavy var(--fail); }}
.loose {{ background:repeating-linear-gradient(45deg, var(--loose), var(--loose) 4px, transparent 4px, transparent 7px);
  outline:1px solid var(--loose-b); border-radius:2px; }}
.chg:target {{ outline:3px solid var(--fg); }}
.chip {{ display:inline-block; font:12px/1 system-ui, sans-serif; padding:4px 8px; border-radius:999px; margin-right:4px; }}
.chip.add {{ color:var(--add-b); }} .chip.xf {{ color:var(--xf-b); }} .chip.interp {{ color:var(--interp-b); }}
.chip.loose {{ color:var(--loose-b); }}
.cards {{ list-style:none; padding:0; display:grid; gap:8px; }}
.card {{ background:var(--card); border:1px solid var(--line); border-left-width:4px; border-radius:8px; padding:10px 14px; }}
.card.add {{ border-left-color:var(--add-b); background:var(--card); }} .card.xf {{ border-left-color:var(--xf-b); background:var(--card); }}
.card.interp {{ border-left-color:var(--interp-b); background:var(--card); }}
.was, .now {{ margin-top:4px; }} .was a, .now a {{ font:12px system-ui, sans-serif; color:var(--muted);
  display:inline-block; width:2.4em; }}
pre.cmd {{ background:var(--card); border:1px solid var(--line); border-radius:8px; padding:12px; overflow-x:auto;
  font:13px/1.5 ui-monospace, Menlo, monospace; }}
</style></head>
<body><main>
<h1>Review: {esc(packet["edition"]["name"])}</h1>
<p class="meta">Original <code>{esc(packet["original"]["name"])}</code> (sha256 {esc(packet["original"]["sha256"][:12])}…) ·
packet <code>{pq}</code></p>
{lineage}
<div class="banner"><b class="{"ok" if packet.get("ok") else "fail"}">{verdict}</b>
<span class="{disk_class}"> · {esc(on_disk)}</span>
{f' · <span class="fail">{loose} unlabelled word(s) marked below</span>' if loose else ""}
<ul>{checks}</ul></div>
<p class="meta">{legend}<span class="chip loose">unlabelled</span>
<span class="chip quote">quotation (underlined)</span></p>
<div class="texts">
<section class="text"><h2>Original</h2><pre>{_segments(packet["original"]["text"], orig_marks)}</pre></section>
<section class="text"><h2>Edition</h2><pre>{_segments(packet["edition"]["text"], ed_marks)}</pre></section>
</div>
<h2>Changes ({len(cards)})</h2>
<ul class="cards">{"".join(cards) or "<li class=meta>none declared</li>"}</ul>
<h2>Quotations</h2>
<ul>{quotes or "<li class=meta>none</li>"}</ul>
<h2>Decide</h2>
<p class="meta">This page records nothing. Run one of these in a terminal (with <code>--home</code> or
<code>$PROSPERO_HOME</code> set):</p>
<pre class="cmd">{commands}</pre>
</main></body></html>
"""


def write_review(packet_text: str, packet_name: str, out_dir: str | Path, source: Source | None = None) -> Path:
    """Write ``<stem>.review.html`` beside the packet and return its path.

    The sheet is a view, so unlike a packet it may be regenerated: an existing
    sheet is replaced. It is still written only into the content folder (it
    contains the original's text), never into this repository, and never
    through a symlink.
    """
    packet = json.loads(packet_text)
    page = render_review(packet, packet_name, source)
    stem = Path(packet_name).name
    stem = stem[: -len(".packet.json")] if stem.endswith(".packet.json") else Path(stem).stem
    folder = _outside_repo(Path(out_dir))
    path = folder / f"{stem}.review.html"
    if path.is_symlink():
        raise RecordError(f"{path.name} is a symlink; refusing to write through it")
    # Never replace one of the packet's own inputs, even an earlier sheet used
    # as an original or edition, or an input that is a link to this name
    # (Copilot on #10). samefile follows links on the input side.
    if source is not None and os.path.lexists(path) and hasattr(source, "path_of"):
        for role in ("original", "edition"):
            try:
                input_path = source.path_of(packet[role]["name"])
            except (SourceError, KeyError, TypeError):
                continue
            if os.path.samefile(input_path, path):
                raise RecordError(f"{path.name} is this packet's {role}; refusing to replace it")
    # Replace only an earlier sheet. Anything else under this name (an input
    # text, a note) is refused, checked by content so no alias can slip by.
    if os.path.lexists(path):
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                first = handle.readline().rstrip("\r\n")
        except OSError as error:
            raise RecordError(f"{path.name} exists and can't be read: {error}") from error
        if first != MARKER or not path.is_file():
            raise RecordError(f"{path.name} exists and is not a review sheet; refusing to replace it")
    folder.mkdir(parents=True, exist_ok=True)
    # Write a temporary file and rename it over the old sheet: the rename
    # replaces a name, so a link planted at the target is not followed.
    # mkstemp creates a new, uniquely named file exclusively, so no existing
    # file (an input text with a ".tmp" name, say) is ever deleted or reused
    # (Codex on #10). Only the file made here is removed on failure.
    fd, tmp_name = tempfile.mkstemp(dir=folder, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(page)
        os.replace(tmp_name, path)
    except BaseException:
        if os.path.lexists(tmp_name):
            os.unlink(tmp_name)
        raise
    return path
