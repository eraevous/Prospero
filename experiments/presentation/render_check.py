"""Render check for the presentation experiment (HO-PRO-20261118-FMYG, DEC-253).

Question it answers: did the renderer change any of the author's characters? The handoff asks to "fail on any
difference from the approved source (no silent quote, dash or other typographic rewriting)".

How it works, in plain terms:
  * The approved source is the Markdown file. Pandoc *reads* it with smart punctuation turned off
    (`markdown-smart`), giving the exact characters the author typed, as a tree (pandoc's JSON AST).
  * The rendered page is read with Python's own HTML parser.
  * From both sides we take three streams of text and compare them character by character, ignoring only
    whitespace (line wrapping is presentation, not wording):
      body  - the running text, in reading order;
      notes - footnote text (renderers move notes to the end, so they get their own stream);
      alts  - image alt texts (they live in attributes, not in visible text).
  * Things a renderer adds that are not words (footnote numbers, back-link arrows) are skipped by their
    standard class names; anything else extra or missing is a failure.

Usage: python3 render_check.py <source.md> <rendered.html>   (exit 0 = identical, 1 = differences)
Standard library only, plus the pandoc binary as the Markdown reader.
"""

import json
import subprocess
import sys
from html.parser import HTMLParser

# Pandoc AST block/inline types whose string content is author text.
_TEXT_LEAVES = {"Str", "Code", "CodeBlock", "Math", "RawInline"}


def source_streams(md_path):
    """Return {'body': str, 'notes': str, 'alts': [str]} from the Markdown source, whitespace removed."""
    ast = json.loads(subprocess.run(
        ["pandoc", "--from=markdown-smart", "--to=json", md_path],
        check=True, capture_output=True, text=True).stdout)
    out = {"body": [], "notes": [], "alts": []}

    def walk(node, stream):
        if isinstance(node, list):
            for item in node:
                walk(item, stream)
            return
        if not isinstance(node, dict) or "t" not in node:
            return
        kind, content = node["t"], node.get("c")
        if kind == "Note":
            walk(content, "notes")
        elif kind == "Image":
            # c = [attr, alt inlines, target]; alt goes to its own list.
            alt = []
            walk_collect(content[1], alt)
            out["alts"].append("".join(alt))
        elif kind == "RawInline" or kind == "RawBlock":
            return  # e.g. HTML comments: not rendered as text
        elif kind in ("Code", "CodeBlock", "Math"):
            out[stream].append(content[-1])
        elif kind == "Str":
            out[stream].append(content)
        else:
            walk(content, stream)

    def walk_collect(node, acc):
        if isinstance(node, list):
            for item in node:
                walk_collect(item, acc)
        elif isinstance(node, dict):
            if node.get("t") == "Str":
                acc.append(node["c"])
            elif node.get("t") in ("Code", "Math"):
                acc.append(node["c"][-1])
            else:
                walk_collect(node.get("c"), acc)

    walk(ast["blocks"], "body")
    squash = lambda s: "".join(s.split())
    return {"body": squash("".join(out["body"])), "notes": squash("".join(out["notes"])),
            "alts": [squash(a) for a in out["alts"]]}


class _Rendered(HTMLParser):
    """Collects body text, footnote text and alt texts from a rendered page."""

    # Elements whose text is never page content.
    SKIP_TAGS = {"head", "script", "style", "template", "noscript"}
    # Renderer-added, non-word marks: pandoc and Quarto both use these class names.
    SKIP_CLASSES = {"footnote-ref", "footnote-back", "anchorjs-link", "quarto-xref"}
    # Footnote containers (pandoc: section.footnotes; Quarto: section.footnotes as well).
    NOTE_CLASSES = {"footnotes"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []  # (tag, mode) where mode is 'skip', 'notes' or None
        self.body, self.notes, self.alts = [], [], []

    def _mode(self):
        for _, mode in reversed(self.stack):
            if mode:
                return mode
        return None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set((attrs.get("class") or "").split())
        if tag == "img":
            if self._mode() != "skip":
                self.alts.append("".join((attrs.get("alt") or "").split()))
            return  # void element
        if tag in ("br", "hr", "meta", "link", "input", "source", "wbr"):
            return
        mode = None
        if tag in self.SKIP_TAGS or classes & self.SKIP_CLASSES or attrs.get("aria-hidden") == "true" and tag != "figcaption":
            mode = "skip"
        elif classes & self.NOTE_CLASSES:
            mode = "notes"
        self.stack.append((tag, mode))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        mode = self._mode()
        if mode == "skip":
            return
        (self.notes if mode == "notes" else self.body).append(data)


def rendered_streams(html_path):
    parser = _Rendered()
    with open(html_path, encoding="utf-8") as fh:
        parser.feed(fh.read())
    squash = lambda parts: "".join("".join(parts).split())
    return {"body": squash(parser.body), "notes": squash(parser.notes), "alts": parser.alts}


def first_difference(a, b):
    """Index of the first differing character, or None if equal."""
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return None if len(a) == len(b) else min(len(a), len(b))


def compare(src, out):
    """Return a list of human-readable differences (empty means the render is faithful)."""
    problems = []
    for key in ("body", "notes"):
        i = first_difference(src[key], out[key])
        if i is not None:
            problems.append(f"{key}: first difference at character {i}: "
                            f"source {src[key][max(0, i - 25):i + 25]!r} vs rendered {out[key][max(0, i - 25):i + 25]!r}")
    if src["alts"] != out["alts"]:
        problems.append(f"alts: source {src['alts']!r} vs rendered {out['alts']!r}")
    return problems


def main(argv):
    if len(argv) != 3:
        print(__doc__.strip().splitlines()[-2], file=sys.stderr)
        return 2
    problems = compare(source_streams(argv[1]), rendered_streams(argv[2]))
    for p in problems:
        print("FAIL", p)
    if not problems:
        print("PASS", argv[2])
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
