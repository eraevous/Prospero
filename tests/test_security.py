"""Security pass, 2026-11-17 (idle work, lane-rules §5): two bugs found by
reproducing them, one test each.

1. ``build`` wrote the packet (which carries the whole original) through a
   ``packets/`` symlink to a folder outside the content folder. ``draft-spec``
   already refused that for its ``--out``; ``build`` now does too.
2. A source file that isn't UTF-8 made every command end in a traceback
   (``UnicodeDecodeError``) instead of ``error: ...`` and exit 1.

Security pass, 2026-11-19 (idle work): a spec that is valid JSON but the wrong
shape (a list, a string, ``"changes": "..."``, a number where text belongs)
made ``build`` end in an ``AttributeError`` traceback or a confusing
``find() argument`` message. Found by the 2026-11-18 content-leak audit
(HO-PRO-20261118-62RW, item 2). ``build_packet`` now checks the spec's shape
first and raises ``SpecError``; the message names the field and the type,
never the value, since a spec quotes the person's writing.

Security pass, 2026-11-22 (idle work): the same for ``review``. A packet is a
JSON file in the person's folder and can be hand-edited or damaged; a wrong
type (a number for a rationale, a string for the change list, a string for a
quotation's locator) ended ``review`` in an ``AttributeError`` traceback.
``render_review`` now checks the packet's shape first and raises
``RecordError``, naming the field and the type, never the value.

Security pass, 2026-11-23 (idle work): writing errors. ``build``, ``decide``
and ``review`` ended in an ``OSError`` traceback when the content folder
couldn't be written: a file named ``packets`` where the packets folder belongs
(``FileExistsError`` from ``mkdir``), or a folder without write permission.
``draft-spec`` already reported these as ``error: ...``; the other three now
do too, and ``build`` never leaves a lone ``.packet.json`` behind.

All text is invented for these tests (synthetic); none of it is anyone's
writing (DEC-183, DEC-184).
"""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from prospero.packet import SourceError, SpecError
from prospero.packet.__main__ import main

from test_packet import SPEC, PacketTestCase


class SecurityPassTest(PacketTestCase):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--home", str(self.home), *args])
        return code, out.getvalue(), err.getvalue()

    def symlink_dir(self, target, link):
        try:
            os.symlink(target, link, target_is_directory=True)
        except (OSError, NotImplementedError) as error:  # e.g. Windows without privilege
            self.skipTest(f"symlinks unavailable: {error}")

    def test_build_refuses_a_packets_folder_symlinked_out_of_the_content_folder(self):
        elsewhere = tempfile.TemporaryDirectory()
        self.addCleanup(elsewhere.cleanup)
        self.symlink_dir(elsewhere.name, self.home / "packets")
        self.write("spec.json", json.dumps(SPEC))
        code, _, err = self.run_cli("build", "original.txt", "edition.txt", "spec.json", "--stem", "p1")
        self.assertEqual(code, 1)
        self.assertIn("outside the content folder", err)
        self.assertEqual(os.listdir(elsewhere.name), [])

    def test_build_still_follows_a_packets_symlink_inside_the_content_folder(self):
        (self.home / "storage").mkdir()
        self.symlink_dir(self.home / "storage", self.home / "packets")
        self.write("spec.json", json.dumps(SPEC))
        code, out, err = self.run_cli("build", "original.txt", "edition.txt", "spec.json", "--stem", "p1")
        self.assertEqual(code, 0, out + err)
        self.assertTrue((self.home / "storage" / "p1.packet.json").is_file())

    def test_a_non_utf8_source_is_an_error_not_a_traceback(self):
        (self.home / "latin1.txt").write_bytes("caf\xe9 au lait\n".encode("latin-1"))
        with self.assertRaises(SourceError):
            self.source.read("latin1.txt")
        code, _, err = self.run_cli("draft-spec", "latin1.txt", "edition.txt", "--out", "spec.json")
        self.assertEqual(code, 1)
        self.assertIn("not UTF-8", err)
        self.assertFalse((self.home / "spec.json").exists())


    # Each case is valid JSON that is not a spec. Before the fix, the first
    # five ended in a traceback and the last two in a TypeError's wording.
    BAD_SPECS = [
        ("a string", "the spec must be a JSON object, not a string"),
        ([SPEC], "the spec must be a JSON object, not a list"),
        (None, "the spec must be a JSON object, not null"),
        ({"changes": "SENTINEL-TEXT"}, "spec 'changes' must be a list, not a string"),
        ({"changes": [7]}, "spec 'changes' entry 1 must be an object, not a number"),
        ({"changes": [{"edition_text": ["SENTINEL-TEXT"]}]},
         "spec 'changes' entry 1: 'edition_text' must be text or null, not a list"),
        ({"quotations": [{"text": {"SENTINEL-TEXT": 1}}]},
         "spec 'quotations' entry 1: 'text' must be text, not an object"),
    ]

    def test_a_wrongly_shaped_spec_is_one_error_line_and_no_packet(self):
        for bad, message in self.BAD_SPECS:
            with self.subTest(spec=bad):
                self.write("spec.json", json.dumps(bad))
                code, out, err = self.run_cli("build", "original.txt", "edition.txt", "spec.json", "--stem", "p1")
                self.assertEqual(code, 1)
                self.assertEqual(err, f"error: {message}\n")
                self.assertNotIn("Traceback", out + err)
                self.assertNotIn("SENTINEL", out + err)  # values never echoed
                self.assertFalse((self.home / "packets").exists())

    def test_build_packet_raises_spec_error_for_library_callers(self):
        with self.assertRaises(SpecError):
            self.build(spec={"changes": [{"rationale": 5}]})
        with self.assertRaises(SpecError):  # true is not text, though bool is an int in Python
            self.build(spec={"changes": [{"id": True}]})

    def test_the_shapes_draft_spec_writes_still_build(self):
        # draft-spec leaves "kind": null and an empty rationale, and adds "_draft";
        # numeric ids are allowed (the builder stringifies them).
        spec = {"_draft": "note", "changes": [{"id": 3, "kind": None, "rationale": "",
                                               "edition_text": None, "original_text": "failed"}],
                "quotations": [{"text": "x", "source": None, "speaker": None}]}
        packet = self.build(spec=spec)
        self.assertFalse(packet.ok)  # unlabelled, as drafted: checks fail, nothing raises
        self.assertEqual(packet.changes[0]["id"], "3")


    # Packet fields that write_packet always fills, set to a wrong type by hand.
    BAD_PACKETS = [
        (lambda p: p.__setitem__("changes", "SENTINEL-TEXT"), "packet 'changes' must be a list, not a string"),
        (lambda p: p["changes"].__setitem__(0, "SENTINEL-TEXT"),
         "packet 'changes' entry 1 must be an object, not a string"),
        (lambda p: p["changes"][0].__setitem__("rationale", 5),
         "packet 'changes' entry 1: 'rationale' must be text or null, not a number"),
        (lambda p: p["changes"][0].__setitem__("original_text", ["SENTINEL-TEXT"]),
         "packet 'changes' entry 1: 'original_text' must be text or null, not a list"),
        (lambda p: p["quotations"][0].__setitem__("locator", "SENTINEL-TEXT"),
         "packet 'quotations' entry 1: 'locator' must be an object, not a string"),
        (lambda p: p["edition"].__setitem__("name", 3), "packet 'edition': 'name' must be text, not a number"),
        (lambda p: p["original"].__setitem__("text", True),
         "packet 'original': 'text' must be text, not true/false"),
        (lambda p: p.__setitem__("checks", ["SENTINEL-TEXT"]),
         "packet 'checks' entry 1 must be an object, not a string"),
        (lambda p: p["checks"][0].__setitem__("problems", [5]),
         "packet 'checks' entry 1: 'problems' item 1 must be text, not a number"),
        (lambda p: p.__setitem__("parent", "SENTINEL-TEXT"),
         "packet 'parent' must be an object or null, not a string"),
    ]

    def test_a_wrongly_shaped_packet_is_one_error_line_and_no_sheet(self):
        packet = self.build().to_dict()
        self.assertTrue(packet["quotations"])  # the locator case needs one
        for damage, message in self.BAD_PACKETS:
            with self.subTest(message=message):
                bad = json.loads(json.dumps(packet))
                damage(bad)
                self.write("bad.packet.json", json.dumps(bad))
                code, out, err = self.run_cli("review", "bad.packet.json")
                self.assertEqual(code, 1)
                self.assertEqual(err, f"error: {message}\n")
                self.assertNotIn("Traceback", out + err)
                self.assertNotIn("SENTINEL", out + err)  # values never echoed
                self.assertFalse((self.home / "bad.review.html").exists())

    def test_a_null_rationale_still_renders(self):
        # The spec allows null where the builder reads empty, so the sheet must too.
        packet = self.build().to_dict()
        packet["changes"][0]["rationale"] = None
        self.write("null.packet.json", json.dumps(packet))
        code, out, err = self.run_cli("review", "null.packet.json")
        self.assertNotIn("Traceback", out + err)
        self.assertTrue((self.home / "null.review.html").exists())


class WriteErrorTest(PacketTestCase):
    """A folder that can't be written is one ``error:`` line and exit 1."""

    run_cli = SecurityPassTest.run_cli

    def assert_error_line(self, result, starts):
        code, out, err = result
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", out + err)
        self.assertEqual(err.count("\n"), 1, err)
        self.assertTrue(err.startswith(f"error: {starts}"), err)

    def write_spec(self):
        self.write("spec.json", json.dumps(SPEC))

    def read_only(self, folder):
        """Make ``folder`` unwritable, or skip where permissions don't bind
        (root ignores them; Windows ignores the mode bits on folders)."""
        if os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0):
            self.skipTest("folder permissions don't bind here (Windows or root)")
        folder.chmod(0o555)
        # tearDown's TemporaryDirectory.cleanup copes with the mode and may
        # already have removed the folder by the time this cleanup runs.
        self.addCleanup(lambda: folder.exists() and folder.chmod(0o755))

    def test_build_with_a_file_named_packets_is_an_error_line(self):
        self.write_spec()
        self.write("packets", "a file, not a folder\n")
        self.assert_error_line(self.run_cli("build", "original.txt", "edition.txt", "spec.json", "--stem", "s"),
                               "packets exists but is not a folder")

    def test_build_into_a_read_only_packets_folder_is_an_error_line(self):
        self.write_spec()
        (self.home / "packets").mkdir()
        self.read_only(self.home / "packets")
        self.assert_error_line(self.run_cli("build", "original.txt", "edition.txt", "spec.json", "--stem", "s"),
                               "can't write s.packet.json")
        self.assertEqual(list((self.home / "packets").iterdir()), [])

    def _built_packet(self):
        self.write_spec()
        code, out, err = self.run_cli("build", "original.txt", "edition.txt", "spec.json", "--stem", "s")
        self.assertEqual(code, 0, err)
        return "packets/s.packet.json"

    def test_decide_in_a_read_only_folder_is_an_error_line(self):
        packet = self._built_packet()
        self.read_only(self.home)
        self.assert_error_line(self.run_cli("decide", packet, "accept", "--by", "tester"),
                               "can't open decisions.jsonl")

    def test_review_in_a_read_only_folder_is_an_error_line(self):
        packet = self._built_packet()
        self.read_only(self.home / "packets")
        self.assert_error_line(self.run_cli("review", packet), "can't write s.review.html")


if __name__ == "__main__":
    unittest.main()
