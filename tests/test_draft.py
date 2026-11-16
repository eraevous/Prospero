"""Tests for draft-spec (prospero/packet/draft.py).

All text is invented for these tests (synthetic); none of it is anyone's
writing (DEC-183, DEC-184).
"""

import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout

from prospero.packet import RecordError, build_packet, draft_spec, write_spec
from prospero.packet.__main__ import main
from prospero.packet.record import REPO_ROOT

from test_packet import EDITION, ORIGINAL, PacketTestCase

# Edits the builder's checks are known to be strict about (see
# test_adversarial.py), each as (original, edition).
CASES = {
    "rewording and an addition": (ORIGINAL, EDITION),
    "repeated word changed at its second occurrence": (
        "the cat saw the dog and the bird.\n", "the cat saw the dog and a bird.\n"),
    "pure deletion": ("We waited. Then we left at once.\n", "We waited. Then we left.\n"),
    "deletion of a repeated word": ("the the cat\n", "the cat\n"),
    "punctuation only": ("Stop, the bell rang.\n", "Stop; the bell rang.\n"),
    "reordering": ("red, green and blue\n", "blue, green and red\n"),
    "quotation marks only": ("She said the tide was early.\n", 'She said "the tide was early."\n'),
    "curly quotation and an addition": ("He said it was over.\n", "He said “it was over.” Then he left.\n"),
    "whole text replaced": ("one two three\n", "four five\n"),
}


def labelled(spec, kind="transformation"):
    """The draft with every blank filled, as a person would."""
    filled = json.loads(json.dumps(spec))
    for change in filled["changes"]:
        change["kind"], change["rationale"] = kind, "test"
    return filled


class DraftTest(PacketTestCase):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--home", str(self.home), *args])
        return code, out.getvalue(), err.getvalue()

    def test_a_labelled_draft_passes_every_check(self):
        # The point of the draft: once labelled, nothing is left unaccounted for.
        for name, (original, edition) in CASES.items():
            with self.subTest(name):
                self.write("original.txt", original)
                self.write("edition.txt", edition)
                spec = labelled(draft_spec(original, edition))
                packet = build_packet(self.source, "original.txt", "edition.txt", spec)
                self.assertTrue(packet.ok, [c for c in packet.checks if not c.ok])

    def test_the_draft_never_chooses_a_label(self):
        spec = draft_spec(ORIGINAL, EDITION)
        self.assertTrue(spec["changes"])
        for change in spec["changes"]:
            self.assertIsNone(change["kind"])
            self.assertEqual(change["rationale"], "")
        packet = build_packet(self.source, "original.txt", "edition.txt", spec)
        self.assertFalse(packet.ok)  # unlabelled until a person labels it

    def test_texts_are_widened_until_they_point_at_the_difference(self):
        original, edition = CASES["repeated word changed at its second occurrence"]
        (change,) = draft_spec(original, edition)["changes"]
        # A bare "the" would first match the opening word; the draft widens it.
        self.assertNotEqual(change["original_text"], "the")
        start = original.find(change["original_text"])
        changed_word = original.find("the bird")
        self.assertTrue(start <= changed_word < start + len(change["original_text"]), change)

    def test_quotations_are_declared_with_their_source(self):
        spec = draft_spec(ORIGINAL, EDITION)
        self.assertEqual(spec["quotations"], [{"text": "the oil was thin this winter.",
                                               "source": "original", "speaker": None}])

    def test_a_quotation_not_in_the_original_gets_a_blank_source(self):
        spec = labelled(draft_spec("He left.\n", 'He left, "never to return."\n'))
        self.assertEqual(spec["quotations"][0]["source"], "")
        self.write("original.txt", "He left.\n")
        self.write("edition.txt", 'He left, "never to return."\n')
        packet = build_packet(self.source, "original.txt", "edition.txt", spec)
        self.assertFalse(next(c for c in packet.checks if c.name == "quotations-resolve").ok)

    def test_identical_texts_draft_nothing(self):
        self.assertEqual(draft_spec(ORIGINAL, ORIGINAL)["changes"], [])

    def test_cli_writes_the_draft_and_refuses_to_overwrite(self):
        code, out, _ = self.run_cli("draft-spec", "original.txt", "edition.txt", "--out", "spec.json")
        self.assertEqual(code, 0, out)
        self.assertIn("2 change(s)", out)
        spec = json.loads((self.home / "spec.json").read_text(encoding="utf-8"))
        self.assertEqual(len(spec["changes"]), 2)
        code, _, err = self.run_cli("draft-spec", "original.txt", "edition.txt", "--out", "spec.json")
        self.assertEqual(code, 1)
        self.assertIn("already exists", err)

    def test_cli_refuses_to_write_outside_the_content_folder(self):
        code, _, err = self.run_cli("draft-spec", "original.txt", "edition.txt", "--out", "../spec.json")
        self.assertEqual(code, 1)
        self.assertIn("outside", err)
        self.assertFalse((self.home.parent / "spec.json").exists())

    def test_cli_refuses_a_dangling_symlink_at_the_output_name(self):
        # spec.json -> other.json (missing) must not create other.json (Codex on #11).
        os.symlink(self.home / "other.json", self.home / "spec.json")
        code, _, err = self.run_cli("draft-spec", "original.txt", "edition.txt", "--out", "spec.json")
        self.assertEqual(code, 1)
        self.assertIn("already exists", err)
        self.assertFalse((self.home / "other.json").exists())

    def test_never_written_inside_the_repository_or_through_a_symlink(self):
        with self.assertRaises(RecordError):
            write_spec({}, REPO_ROOT / "tests" / "draft.spec.json")
        self.assertFalse((REPO_ROOT / "tests" / "draft.spec.json").exists())
        target = self.home / "keep.txt"
        target.write_text("keep me\n", encoding="utf-8")
        os.symlink(target, self.home / "spec.json")
        with self.assertRaises(RecordError):
            write_spec({}, self.home / "spec.json")
        self.assertEqual(target.read_text(encoding="utf-8"), "keep me\n")


if __name__ == "__main__":
    unittest.main()
