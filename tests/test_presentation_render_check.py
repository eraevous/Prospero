"""Tests for the presentation experiment's render check (HO-PRO-20261118-FMYG, DEC-253).

The check must pass a faithful render and fail one that rewrites quotes or dashes, drops a word, or changes
alt text. It reads Markdown through the pandoc binary, an external tool the experiment uses (not a project
dependency), so these tests skip when pandoc is not installed.
"""

import importlib.util
import os
import shutil
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.join(HERE, "..", "experiments", "presentation")

spec = importlib.util.spec_from_file_location("render_check", os.path.join(EXP, "render_check.py"))
render_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render_check)

# Invented text for the test.
SOURCE = """---
pagetitle: t
---

A "quoted" word -- and it's done...[^n]

![a 'small' picture](p.svg)

[^n]: Note with "quotes".
"""

FAITHFUL = """<html><head><title>t</title></head><body>
<p>A "quoted" word -- and it's done...<a class="footnote-ref" href="#fn1"><sup>1</sup></a></p>
<figure><img src="p.svg" alt="a 'small' picture" /><figcaption aria-hidden="true">a 'small' picture</figcaption></figure>
<section class="footnotes"><hr /><ol><li><p>Note with "quotes".<a class="footnote-back" href="#r">&#8617;</a></p></li></ol></section>
</body></html>"""


@unittest.skipUnless(shutil.which("pandoc"), "pandoc not installed")
class RenderCheckTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.src = os.path.join(self.dir, "s.md")
        with open(self.src, "w", encoding="utf-8") as fh:
            fh.write(SOURCE)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def problems(self, html):
        path = os.path.join(self.dir, "r.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
        return render_check.compare(render_check.source_streams(self.src), render_check.rendered_streams(path))

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

    def test_whitespace_and_wrapping_ignored(self):
        self.assertEqual(self.problems(FAITHFUL.replace("A \"quoted\" word", "A\n  \"quoted\"\n word")), [])


if __name__ == "__main__":
    unittest.main()
