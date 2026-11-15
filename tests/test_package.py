"""Smoke test: the package imports and declares a version.

The package imports and its version is a dotted string. Feature tests live
beside this one (test_packet.py).
"""

import unittest

import prospero


class PackageTest(unittest.TestCase):
    def test_version_is_a_dotted_string(self):
        # A version string such as "0.0.0": three dot-separated integers.
        parts = prospero.__version__.split(".")
        self.assertEqual(len(parts), 3)
        self.assertTrue(all(part.isdigit() for part in parts))


if __name__ == "__main__":
    unittest.main()
