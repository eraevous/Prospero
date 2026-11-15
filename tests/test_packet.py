"""Tests for the editorial packet (HO-PRO-20261109-CDAD).

All text here is invented for these tests (synthetic). None of it is anyone's
writing; Zach's works never appear in this repository (DEC-183, DEC-184).
Each test builds a throwaway content folder in a temporary directory.
"""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from prospero.packet import (FolderSource, RecordError, SourceError, build_packet,
                             content_home, record_decision, write_packet)
from prospero.packet.__main__ import main
from prospero.packet.record import REPO_ROOT

# An invented original: a lighthouse keeper's log entry.
ORIGINAL = (
    "The lamp failed at nine.\n"
    "Marta said the oil was thin this winter.\n"
    "We relit it by hand and kept watch until dawn.\n"
)

# A proposed edition: one rewording, one added sentence, one quotation.
EDITION = (
    "The lamp went dark at nine.\n"
    "Marta said \"the oil was thin this winter.\"\n"
    "We relit it by hand and kept watch until dawn.\n"
    "Nobody slept.\n"
)

SPEC = {
    "changes": [
        {"id": "c1", "kind": "transformation", "rationale": "plainer verb",
         "original_text": "failed", "edition_text": "went dark"},
        {"id": "c2", "kind": "agent addition", "rationale": "closes the scene",
         "edition_text": "Nobody slept."},
    ],
    "quotations": [{"text": "the oil was thin this winter.", "source": "original", "speaker": "Marta"}],
}


class PacketTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name) / "content"
        self.home.mkdir()
        self.write("original.txt", ORIGINAL)
        self.write("edition.txt", EDITION)
        self.source = FolderSource(self.home)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name, text):
        (self.home / name).write_text(text, encoding="utf-8", newline="")

    def build(self, spec=SPEC, edition=None):
        if edition is not None:
            self.write("edition.txt", edition)
        return build_packet(self.source, "original.txt", "edition.txt", spec)

    def check(self, packet, name):
        return next(c for c in packet.checks if c.name == name)


class BuildTest(PacketTestCase):
    def test_well_formed_packet_passes_every_check(self):
        packet = self.build()
        self.assertTrue(packet.ok, [c for c in packet.checks if not c.ok])
        self.assertEqual(packet.original, ORIGINAL)

    def test_quotation_resolves_to_a_locator_in_the_original(self):
        quote = self.build().quotations[0]
        self.assertEqual(quote["speaker"], "Marta")
        self.assertEqual(quote["locator"]["name"], "original.txt")
        self.assertEqual(quote["locator"]["line"], 2)
        self.assertEqual(ORIGINAL[quote["locator"]["offset"]:].split("\n")[0], "the oil was thin this winter.")

    def test_quotation_that_is_not_word_for_word_fails(self):
        edition = EDITION.replace("the oil was thin", "the oil ran thin")
        spec = dict(SPEC, quotations=[{"text": "the oil ran thin this winter.", "source": "original"}])
        check = self.check(self.build(spec, edition), "quotations-resolve")
        self.assertFalse(check.ok)
        self.assertIn("word for word", check.problems[0])

    def test_undeclared_quotation_fails(self):
        check = self.check(self.build(dict(SPEC, quotations=[])), "quotations-resolve")
        self.assertFalse(check.ok)
        self.assertIn("not declared", check.problems[0])

    def test_quotation_can_resolve_to_another_named_source(self):
        self.write("letter.txt", "Bring more oil before the storm.\n")
        edition = EDITION + "The letter read “Bring more oil before the storm.”\n"
        spec = {
            "changes": SPEC["changes"] + [{"id": "c3", "kind": "agent addition", "rationale": "context",
                                           "edition_text": "The letter read"}],
            "quotations": SPEC["quotations"] + [{"text": "Bring more oil before the storm.", "source": "letter.txt"}],
        }
        packet = self.build(spec, edition)
        self.assertTrue(packet.ok, [c for c in packet.checks if not c.ok])
        self.assertEqual(packet.quotations[1]["locator"]["name"], "letter.txt")

    def test_unlabelled_change_fails(self):
        spec = dict(SPEC, changes=SPEC["changes"][:1])  # drop the label for "Nobody slept."
        check = self.check(self.build(spec), "changes-labelled")
        self.assertFalse(check.ok)
        self.assertTrue(any("Nobody slept." in p for p in check.problems))

    def test_unlabelled_deletion_fails(self):
        edition = EDITION.replace("We relit it by hand and kept watch until dawn.\n", "")
        check = self.check(self.build(SPEC, edition), "changes-labelled")
        self.assertFalse(check.ok)
        self.assertTrue(any("We relit" in p and "original line 3" in p for p in check.problems))

    def test_labelled_deletion_passes(self):
        edition = EDITION.replace("We relit it by hand and kept watch until dawn.\n", "")
        spec = dict(SPEC, changes=SPEC["changes"] + [
            {"id": "c3", "kind": "transformation", "rationale": "tighter",
             "original_text": "We relit it by hand and kept watch until dawn."}])
        self.assertTrue(self.build(spec, edition).ok)

    def test_labelled_addition_cannot_vouch_for_a_neighbouring_rewrite(self):
        # difflib merges "hand and kept watch until dawn." -> "hand." with the
        # labelled "Nobody slept." on the next line into one replacement. The
        # unlabelled cut must still be reported.
        edition = EDITION.replace(" and kept watch until dawn", "")
        check = self.check(self.build(SPEC, edition), "changes-labelled")
        self.assertFalse(check.ok)
        self.assertTrue(any("'hand.'" in p for p in check.problems))

    def test_unknown_kind_or_missing_rationale_fails(self):
        spec = dict(SPEC, changes=[dict(SPEC["changes"][0], kind="polish"),
                                   dict(SPEC["changes"][1], rationale="")])
        problems = self.check(self.build(spec), "changes-labelled").problems
        self.assertTrue(any("'polish'" in p for p in problems))
        self.assertTrue(any("no rationale" in p for p in problems))

    def test_interpretation_inside_quotation_marks_fails(self):
        # The agent's reading of Marta, presented as if she had said it.
        edition = EDITION.replace("Nobody slept.", "Marta said \"the keeper was afraid.\"")
        spec = {
            "changes": [SPEC["changes"][0],
                        {"id": "c2", "kind": "interpretation", "rationale": "what Marta meant",
                         "edition_text": "the keeper was afraid."},
                        {"id": "c3", "kind": "agent addition", "rationale": "attribution",
                         "edition_text": "Marta said \"the keeper"}],
            "quotations": SPEC["quotations"] + [{"text": "the keeper was afraid.", "source": "original"}],
        }
        packet = self.build(spec, edition)
        self.assertFalse(self.check(packet, "no-interpretation-as-quotation").ok)
        # It also fails to resolve, since nobody wrote those words.
        self.assertFalse(self.check(packet, "quotations-resolve").ok)

    def test_interpretation_outside_quotation_marks_is_fine(self):
        edition = EDITION.replace("Nobody slept.", "The keeper, it seems, was afraid.")
        spec = dict(SPEC, changes=[SPEC["changes"][0],
                                   {"id": "c2", "kind": "interpretation", "rationale": "a reading, marked as one",
                                    "edition_text": "The keeper, it seems, was afraid."}])
        self.assertTrue(self.build(spec, edition).ok)

    def test_original_hash_matches_the_file_bytes(self):
        import hashlib
        packet = self.build()
        self.assertEqual(packet.original_sha256,
                         hashlib.sha256((self.home / "original.txt").read_bytes()).hexdigest())


class SourceTest(PacketTestCase):
    def test_folder_source_refuses_paths_outside_the_folder(self):
        (Path(self._tmp.name) / "outside.txt").write_text("private", encoding="utf-8")
        with self.assertRaises(SourceError):
            self.source.read("../outside.txt")
        with self.assertRaises(SourceError):
            self.source.read(str(Path(self._tmp.name) / "outside.txt"))

    def test_content_home_has_no_default(self):
        saved = os.environ.pop("PROSPERO_HOME", None)
        try:
            with self.assertRaises(SourceError):
                content_home()
        finally:
            if saved is not None:
                os.environ["PROSPERO_HOME"] = saved


class RecordTest(PacketTestCase):
    def test_write_packet_writes_json_and_markdown_and_never_overwrites(self):
        json_path, md_path = write_packet(self.build(), self.home / "packets", "lamp")
        data = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(data["original"]["text"], ORIGINAL)
        self.assertTrue(data["ok"])
        self.assertIn("Marta, original.txt line 2", md_path.read_text(encoding="utf-8"))
        with self.assertRaises(RecordError):
            write_packet(self.build(), self.home / "packets", "lamp")

    def test_refuses_to_write_inside_the_repository(self):
        with self.assertRaises(RecordError):
            write_packet(self.build(), REPO_ROOT / "packets", "lamp")
        with self.assertRaises(RecordError):
            record_decision(REPO_ROOT, self.build().to_dict(), self.source, "accept", "zach")

    def test_reject_appends_a_line_and_leaves_the_original_untouched(self):
        before = (self.home / "original.txt").read_bytes()
        packet = self.build().to_dict()
        record_decision(self.home, packet, self.source, "accept", "zach", "first try")
        entry = record_decision(self.home, packet, self.source, "reject", "zach", "keep the original")
        lines = (self.home / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(l)["decision"] for l in lines], ["accept", "reject"])
        self.assertEqual(entry["original_sha256"], packet["original"]["sha256"])
        self.assertEqual((self.home / "original.txt").read_bytes(), before)

    def test_decision_refused_when_original_changed_since_the_packet(self):
        packet = self.build().to_dict()
        self.write("original.txt", ORIGINAL + "An extra line.\n")
        with self.assertRaises(RecordError):
            record_decision(self.home, packet, self.source, "accept", "zach")
        self.assertFalse((self.home / "decisions.jsonl").exists())

    def test_decision_must_be_known_and_have_a_decider(self):
        packet = self.build().to_dict()
        with self.assertRaises(RecordError):
            record_decision(self.home, packet, self.source, "maybe", "zach")
        with self.assertRaises(RecordError):
            record_decision(self.home, packet, self.source, "accept", " ")


class CommandLineTest(PacketTestCase):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--home", str(self.home), *args])
        return code, out.getvalue(), err.getvalue()

    def test_build_then_decide(self):
        self.write("spec.json", json.dumps(SPEC))
        code, out, _ = self.run_cli("build", "original.txt", "edition.txt", "spec.json", "--stem", "lamp")
        self.assertEqual(code, 0, out)
        code, out, _ = self.run_cli("decide", "packets/lamp.packet.json", "revise", "--by", "zach")
        self.assertEqual(code, 0)
        self.assertIn("recorded revise", out)

    def test_build_exits_1_and_lists_problems_when_a_check_fails(self):
        self.write("spec.json", json.dumps(dict(SPEC, quotations=[])))
        code, out, _ = self.run_cli("build", "original.txt", "edition.txt", "spec.json", "--stem", "lamp")
        self.assertEqual(code, 1)
        self.assertIn("not declared", out)


class ManifestTest(unittest.TestCase):
    def test_manifest_declares_the_information_sockets(self):
        manifest = json.loads((REPO_ROOT / "prospero" / "packet" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["tool"], "prospero.packet")
        self.assertTrue(manifest["sockets"]["information_in"])
        self.assertTrue(manifest["sockets"]["information_out"])
        self.assertFalse(manifest["network"])


if __name__ == "__main__":
    unittest.main()
