"""Tests for the review sheet (prospero/packet/review.py).

All text is invented for these tests (synthetic), reusing the lighthouse log
from test_packet.py. None of it is anyone's writing (DEC-183, DEC-184).
"""

import io
import json
import os
import re
import unittest
from contextlib import redirect_stderr, redirect_stdout

from prospero.packet import RecordError, render_review, write_packet, write_review
from prospero.packet.__main__ import main
from prospero.packet.record import REPO_ROOT

from test_packet import EDITION, SPEC, PacketTestCase


def classes_of(page, anchor):
    """The CSS classes on the element with id ``anchor``, as a set."""
    match = re.search(r'class="([^"]*)" id="%s"' % re.escape(anchor), page)
    return set(match.group(1).split()) if match else set()


# A highlighted piece of text marked unlabelled (the legend's chip doesn't count).
LOOSE_MARK = r'<span class="(?![^"]*chip)[^"]*\bloose\b'


class ReviewTest(PacketTestCase):
    def packet_dict(self, spec=SPEC, edition=None):
        return self.build(spec, edition).to_dict()

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--home", str(self.home), *args])
        return code, out.getvalue(), err.getvalue()

    def test_every_change_is_highlighted_in_both_texts_by_label(self):
        page = render_review(self.packet_dict(), source=self.source)
        self.assertEqual(classes_of(page, "o:c1"), {"chg", "xf"})    # "failed" in the original
        self.assertEqual(classes_of(page, "e:c1"), {"chg", "xf"})    # "went dark" in the edition
        self.assertEqual(classes_of(page, "e:c2"), {"chg", "add"})   # the added sentence
        self.assertIn('href="#o:c1"', page)                   # the card links to both
        self.assertIn("All checks passed", page)
        self.assertIn("original on disk matches the packet", page)
        self.assertNotRegex(page, LOOSE_MARK)

    def test_an_unlabelled_difference_is_marked_where_it_is(self):
        edition = EDITION.replace("kept watch", "kept a long watch")
        page = render_review(self.packet_dict(edition=edition), source=self.source)
        self.assertIn("Checks FAILED", page)
        self.assertIn('<span class="loose">a</span>', page)
        self.assertIn('<span class="loose">long</span>', page)
        self.assertIn("2 unlabelled word(s)", page)

    def test_quotation_is_underlined_in_both_texts(self):
        page = render_review(self.packet_dict(), source=self.source)
        self.assertEqual(page.count('<span class="quote">the oil was thin this winter.</span>'), 2)
        self.assertIn("(Marta)", page)

    def test_text_from_the_packet_is_escaped(self):
        # A hostile edition or rationale must not become markup in the sheet.
        edition = EDITION.replace("Nobody slept.", "<script>alert(1)</script>")
        spec = json.loads(json.dumps(SPEC))
        spec["changes"][1].update(edition_text="<script>alert(1)</script>", rationale='"><img src=x>')
        page = render_review(self.packet_dict(spec, edition), source=self.source)
        self.assertNotIn("<script>", page)
        self.assertNotIn("<img", page)
        self.assertIn("&lt;script&gt;", page)

    def test_the_sheet_is_self_contained(self):
        page = render_review(self.packet_dict(), source=self.source)
        self.assertNotRegex(page, r"<script|<link|src=|https?://")

    def test_a_changed_original_is_flagged(self):
        packet = self.packet_dict()
        self.write("original.txt", "Someone edited this.\n")
        page = render_review(packet, source=self.source)
        self.assertIn("the original has changed since this packet was built", page)

    def test_overlapping_marks_split_without_nesting(self):
        spec = json.loads(json.dumps(SPEC))
        spec["changes"].append({"id": "c3", "kind": "interpretation", "rationale": "overlap",
                                "edition_text": "went dark at nine"})
        page = render_review(self.packet_dict(spec), source=self.source)
        self.assertEqual(classes_of(page, "e:c1"), {"chg", "interp", "xf"})
        self.assertIn('id="e:c3"', page)
        self.assertEqual(len(re.findall(r'id="e:c1"', page)), 1)  # ids stay unique

    def test_a_word_covered_by_two_changes_together_is_not_unlabelled(self):
        # The builder accepts coverage by the union of spans; the sheet must agree.
        edition = EDITION.replace("Nobody slept.", "Nobody dozed.")
        spec = json.loads(json.dumps(SPEC))
        spec["changes"][1]["edition_text"] = "Nobody do"
        spec["changes"].append({"id": "c3", "kind": "agent addition", "rationale": "split", "edition_text": "zed."})
        packet = self.packet_dict(spec, edition)
        self.assertTrue(packet["ok"], packet["checks"])
        self.assertNotRegex(render_review(packet, source=self.source), LOOSE_MARK)

    def test_decide_commands_shell_quote_the_packet_name(self):
        page = render_review(self.packet_dict(), "packets/first draft;rm x.packet.json", self.source)
        self.assertIn("decide &#x27;packets/first draft;rm x.packet.json&#x27; accept", page)

    def test_an_input_text_with_the_sheets_name_is_never_replaced(self):
        # An original named like the sheet, beside the packet (Codex on #10).
        folder = self.home / "packets"
        folder.mkdir()
        (folder / "first.review.html").write_text(EDITION, encoding="utf-8")
        with self.assertRaises(RecordError):
            write_review(json.dumps(self.packet_dict()), "first.packet.json", folder)
        self.assertEqual((folder / "first.review.html").read_text(encoding="utf-8"), EDITION)

    def test_the_quotation_mark_sits_on_the_quoted_occurrence(self):
        # The quoted words also appear earlier, unquoted (Codex on #10).
        self.write("original.txt", "cat\n")
        edition = 'cat "cat"\n'
        spec = {"changes": [{"id": "c1", "kind": "agent addition", "rationale": "echo", "edition_text": "cat "}],
                "quotations": [{"text": "cat", "source": "original"}]}
        packet = self.packet_dict(spec, edition)
        self.assertTrue(packet["ok"], packet["checks"])
        page = render_review(packet, source=self.source)
        self.assertIn('&quot;<span class="quote">cat</span>&quot;', page)

    def test_every_change_link_has_a_target_when_spans_coincide(self):
        # Two changes on the same words (Codex on #10).
        spec = json.loads(json.dumps(SPEC))
        spec["changes"].append(dict(spec["changes"][0], id="c9"))
        packet = self.packet_dict(spec)
        self.assertTrue(packet["ok"], packet["checks"])
        page = render_review(packet, source=self.source)
        for anchor in ("o:c1", "e:c1", "o:c9", "e:c9"):
            self.assertEqual(page.count(f'id="{anchor}"'), 1, anchor)

    def test_a_file_with_the_old_temporary_name_is_left_alone(self):
        # The earlier fixed ".<sheet>.tmp" name could delete an input (Codex on #10).
        folder = self.home / "packets"
        folder.mkdir()
        keep = folder / ".first.review.html.tmp"
        keep.write_text("keep me\n", encoding="utf-8")
        write_review(json.dumps(self.packet_dict()), "first.packet.json", folder)
        self.assertEqual(keep.read_text(encoding="utf-8"), "keep me\n")
        self.assertEqual(sorted(p.name for p in folder.iterdir()), [".first.review.html.tmp", "first.review.html"])

    def test_not_a_packet_is_refused(self):
        with self.assertRaises(RecordError):
            render_review({"format": "something else"})

    def test_cli_writes_beside_the_packet_and_can_regenerate(self):
        write_packet(self.build(), self.home / "packets", "first")
        for _ in range(2):  # a sheet is a view: writing it again replaces it
            code, out, _ = self.run_cli("review", "packets/first.packet.json")
            self.assertEqual(code, 0, out)
        self.assertTrue((self.home / "packets" / "first.review.html").is_file())
        self.assertFalse(any(p.name.endswith(".tmp") for p in (self.home / "packets").iterdir()))

    def test_cli_exits_1_for_a_failed_packet_or_a_changed_original(self):
        write_packet(self.build(edition=EDITION + "Extra.\n"), self.home / "packets", "bad")
        code, out, _ = self.run_cli("review", "packets/bad.packet.json")
        self.assertEqual(code, 1)
        self.assertIn("FAILED", out)
        self.assertTrue((self.home / "packets" / "bad.review.html").is_file())

        self.write("edition.txt", EDITION)
        write_packet(self.build(), self.home / "packets", "good")
        self.write("original.txt", "Someone edited this.\n")
        code, out, _ = self.run_cli("review", "packets/good.packet.json")
        self.assertEqual(code, 1)
        self.assertIn("has changed", out)

    def test_cli_refuses_a_packet_outside_the_content_folder(self):
        code, _, err = self.run_cli("review", "../outside.packet.json")
        self.assertEqual(code, 1)
        self.assertIn("error", err)

    def test_never_written_inside_the_repository(self):
        text = json.dumps(self.packet_dict())
        with self.assertRaises(RecordError):
            write_review(text, "first.packet.json", REPO_ROOT / "tests")
        self.assertFalse((REPO_ROOT / "tests" / "first.review.html").exists())

    def test_a_symlinked_sheet_is_not_written_through(self):
        target = self.home / "victim.txt"
        target.write_text("keep me\n", encoding="utf-8")
        folder = self.home / "packets"
        folder.mkdir()
        os.symlink(target, folder / "first.review.html")
        with self.assertRaises(RecordError):
            write_review(json.dumps(self.packet_dict()), "first.packet.json", folder)
        self.assertEqual(target.read_text(encoding="utf-8"), "keep me\n")


if __name__ == "__main__":
    unittest.main()
