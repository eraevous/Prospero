"""Tests for the presentation experiment's render check (HO-PRO-20261118-FMYG, DEC-253).

The check must pass a faithful render and fail one that rewrites quotes or dashes, drops a word, or changes
alt text. The check normally reads Markdown through the pandoc binary (an external tool for the experiment, not a
project dependency); these tests use the AST pandoc 3.1.3 wrote for fixtures/check-source.md, checked in as
fixtures/check-source.ast.json, so they run without pandoc.
"""

import importlib.util
import os
import json
import shutil
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.join(HERE, "..", "experiments", "presentation")

spec = importlib.util.spec_from_file_location("render_check", os.path.join(EXP, "render_check.py"))
render_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render_check)

# Invented text for the test: fixtures/check-source.md, read as pandoc's AST.
with open(os.path.join(EXP, "fixtures", "check-source.ast.json"), encoding="utf-8") as _fh:
    SOURCE_AST = json.load(_fh)

FAITHFUL = """<html><head><title>t</title></head><body>
<p>A "quoted" word -- and it's done...<a class="footnote-ref" href="#fn1"><sup>1</sup></a></p>
<figure><img src="p.svg" alt="a 'small' picture" /><figcaption aria-hidden="true">a 'small' picture</figcaption></figure>
<section class="footnotes"><hr /><ol><li><p>Note with "quotes".<a class="footnote-back" href="#r">&#8617;</a></p></li></ol></section>
</body></html>"""

# fixtures/note-image.md as pandoc 3.1.3 renders it (standalone page trimmed): the note, and its image, come last.
NOTE_IMAGE = """<html><head><title>t</title></head><body>
<p>Body text.<a href="#fn1" class="footnote-ref" id="fnref1"><sup>1</sup></a></p>
<figure><img src="b.svg" alt="body pic" /><figcaption aria-hidden="true">body pic</figcaption></figure>
<aside id="footnotes" class="footnotes footnotes-end-of-document"><hr /><ol>
<li id="fn1"><p>Note <img src="n.svg" alt="note pic" /> here.<a href="#fnref1" class="footnote-back">&#8617;&#65038;</a></p></li>
</ol></aside>
</body></html>"""


class RenderCheckTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def problems(self, html):
        path = os.path.join(self.dir, "r.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
        return render_check.compare(render_check.streams_from_ast(SOURCE_AST), render_check.rendered_streams(path))

    def test_faithful_render_passes(self):
        self.assertEqual(self.problems(FAITHFUL), [])

    def test_curly_quotes_fail(self):
        self.assertTrue(self.problems(FAITHFUL.replace('"quoted"', "“quoted”")))

    def test_en_dash_fails(self):
        self.assertTrue(self.problems(FAITHFUL.replace(" -- ", " – ")))

    def test_ellipsis_fails(self):
        self.assertTrue(self.problems(FAITHFUL.replace("done...", "done…")))

    def test_note_rewrite_fails(self):
        self.assertTrue(self.problems(FAITHFUL.replace('Note with "quotes"', "Note with “quotes”")))

    def test_dropped_word_fails(self):
        self.assertTrue(self.problems(FAITHFUL.replace("word ", "")))

    def test_alt_change_fails(self):
        self.assertTrue(self.problems(FAITHFUL.replace("alt=\"a 'small' picture\"", 'alt="a picture"')))

    def test_aria_hidden_prose_counts(self):
        # Review finding (Copilot, PR #16): aria-hidden text is still visible, so added prose there must fail.
        self.assertTrue(self.problems(FAITHFUL.replace("<section", '<p aria-hidden="true">Unexpected added prose.</p><section')))

    def test_raw_html_text_counts(self):
        # Review finding (Copilot, PR #16): visible text in raw HTML is author text, not nothing.
        ast = json.loads(json.dumps(SOURCE_AST))
        ast["blocks"].append({"t": "RawBlock", "c": ["html", "<p>Keep this line.</p><!-- a comment -->"]})
        src = render_check.streams_from_ast(ast)
        faithful = FAITHFUL.replace("<section", "<p>Keep this line.</p><section")
        for html, ok in ((faithful, True), (FAITHFUL, False)):
            path = os.path.join(self.dir, "r.html")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(html)
            self.assertEqual(render_check.compare(src, render_check.rendered_streams(path)) == [], ok)

    def test_other_raw_formats_refused(self):
        ast = json.loads(json.dumps(SOURCE_AST))
        ast["blocks"].append({"t": "RawBlock", "c": ["latex", "\\newpage"]})
        with self.assertRaises(render_check.UnsupportedSource):
            render_check.streams_from_ast(ast)

    def test_note_image_moves_with_its_note(self):
        # Review finding (Codex P2, PR #16): pandoc moves a note to the end, so an image inside a note that comes
        # before a body image is rendered after it. Alt texts are compared per stream, so a faithful render passes.
        with open(os.path.join(EXP, "fixtures", "note-image.ast.json"), encoding="utf-8") as fh:
            src = render_check.streams_from_ast(json.load(fh))
        self.assertEqual((src["alts"], src["note_alts"]), (["bodypic"], ["notepic"]))
        for html, ok in ((NOTE_IMAGE, True),
                         (NOTE_IMAGE.replace('alt="note pic"', 'alt="note picture"'), False),
                         # The same alt text moved out of the note into the body is a difference, not a match.
                         (NOTE_IMAGE.replace('<img src="n.svg" alt="note pic" /> ', "")
                                    .replace('alt="body pic" />', 'alt="body pic" /><img src="n.svg" alt="note pic" />'),
                          False)):
            path = os.path.join(self.dir, "r.html")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(html)
            self.assertEqual(render_check.compare(src, render_check.rendered_streams(path)) == [], ok, html)

    def test_whitespace_and_wrapping_ignored(self):
        self.assertEqual(self.problems(FAITHFUL.replace("A \"quoted\" word", "A\n  \"quoted\"\n word")), [])


if __name__ == "__main__":
    unittest.main()
