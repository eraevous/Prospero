"""Security pass, 2026-11-17 (idle work, lane-rules §5): two bugs found by
reproducing them, one test each.

1. ``build`` wrote the packet (which carries the whole original) through a
   ``packets/`` symlink to a folder outside the content folder. ``draft-spec``
   already refused that for its ``--out``; ``build`` now does too.
2. A source file that isn't UTF-8 made every command end in a traceback
   (``UnicodeDecodeError``) instead of ``error: ...`` and exit 1.

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

from prospero.packet import SourceError
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


if __name__ == "__main__":
    unittest.main()
