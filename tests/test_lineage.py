"""Tests for revision lineage and history (increment 2, HO-PRO-20261116-P8CB).

The acceptance checks come from Kate (API instance, 2026-11-16): immutable
lineage, fail closed on broken ancestry, keep branches without picking a
winner, keep recorded decisions apart from any derived state. All text is
invented for these tests (DEC-183, DEC-184).
"""

import io
import json
from contextlib import redirect_stderr, redirect_stdout

from prospero.packet import LineageError, history, parent_ref, record_decision, write_packet
from prospero.packet.__main__ import main
from prospero.packet.build import build_packet, sha256

from test_packet import EDITION, ORIGINAL, SPEC, PacketTestCase

# A second edition that revises the first: one more transformation.
EDITION_2 = EDITION.replace("Nobody slept.", "Nobody slept that night.")
SPEC_2 = {
    "changes": SPEC["changes"][:1] + [
        {"id": "c2", "kind": "agent addition", "rationale": "closes the scene, with a time",
         "edition_text": "Nobody slept that night."},
    ],
    "quotations": SPEC["quotations"],
}
# A sibling revision of the same parent, taking the scene another way.
EDITION_3 = EDITION.replace("Nobody slept.", "The gulls came back at first light.")
SPEC_3 = dict(SPEC_2, changes=SPEC["changes"][:1] + [
    {"id": "c2", "kind": "agent addition", "rationale": "ends on the morning",
     "edition_text": "The gulls came back at first light."}])


class LineageTestCase(PacketTestCase):
    def make(self, stem, edition, spec, parent=None):
        """Build and write a packet; return its name under the content folder."""
        name = f"{stem}.txt"
        self.write(name, edition)
        ref = parent_ref(self.source, parent, "original.txt") if parent else None
        packet = build_packet(self.source, "original.txt", name, spec, parent=ref)
        self.assertTrue(packet.ok, [c.problems for c in packet.checks])
        write_packet(packet, self.home / "packets", stem)
        return f"packets/{stem}.packet.json"

    def decide(self, packet_name, decision, by="zach"):
        text = self.source.read(packet_name)
        return record_decision(self.home, json.loads(text), self.source, decision, by,
                               packet_name=packet_name, packet_sha256=sha256(text))

    def read_bytes(self, name):
        return (self.home / name).read_bytes()


class RevisionTest(LineageTestCase):
    def test_revision_names_its_parent_by_hash_and_leaves_the_parent_alone(self):
        first = self.make("first", EDITION, SPEC)
        self.decide(first, "revise")
        before = {name: self.read_bytes(name) for name in (first, "decisions.jsonl", "original.txt")}
        second = self.make("second", EDITION_2, SPEC_2, parent=first)
        child = json.loads(self.source.read(second))
        self.assertEqual(child["parent"], {"name": first, "sha256": sha256(self.source.read(first))})
        self.assertEqual(child["original"]["sha256"], sha256(ORIGINAL))
        for name, data in before.items():
            self.assertEqual(self.read_bytes(name), data, name)

    def test_first_packet_has_no_parent(self):
        self.assertIsNone(json.loads(self.source.read(self.make("first", EDITION, SPEC)))["parent"])

    def test_parent_for_another_original_is_refused(self):
        self.write("other.txt", "A different log.\n")
        other = build_packet(self.source, "other.txt", "other.txt", {"changes": [], "quotations": []})
        write_packet(other, self.home / "packets", "other")
        with self.assertRaises(LineageError):
            parent_ref(self.source, "packets/other.packet.json", "original.txt")

    def test_parent_built_from_older_bytes_of_the_original_is_refused(self):
        first = self.make("first", EDITION, SPEC)
        self.write("original.txt", ORIGINAL + "A late entry.\n")
        with self.assertRaises(LineageError):
            parent_ref(self.source, first, "original.txt")

    def test_parent_that_is_not_a_packet_is_refused(self):
        self.write("notes.json", "[1, 2]")
        with self.assertRaises(LineageError):
            parent_ref(self.source, "notes.json", "original.txt")


class HistoryTest(LineageTestCase):
    def test_history_shows_the_chain_and_decisions_in_order(self):
        first = self.make("first", EDITION, SPEC)
        self.decide(first, "revise")
        second = self.make("second", EDITION_2, SPEC_2, parent=first)
        self.decide(second, "accept")
        h = history(self.source, "original.txt")
        self.assertTrue(h.ok, h.problems)
        self.assertEqual(h.roots(), [first])
        self.assertEqual(h.packets[first].children, [second])
        self.assertEqual([(e["decision"], e["packets"]) for e in h.events],
                         [("revise", [first]), ("accept", [second])])

    def test_two_revisions_of_one_parent_are_both_shown_and_no_winner_is_picked(self):
        first = self.make("first", EDITION, SPEC)
        second = self.make("second", EDITION_2, SPEC_2, parent=first)
        third = self.make("third", EDITION_3, SPEC_3, parent=first)
        self.decide(third, "accept")
        self.decide(second, "accept")
        h = history(self.source, "original.txt")
        self.assertTrue(h.ok, h.problems)
        self.assertEqual(h.packets[first].children, [second, third])
        # Both acceptances are reported as recorded; nothing says which is "current".
        self.assertEqual([e["packets"] for e in h.events], [[third], [second]])
        self.assertNotIn("current", json.dumps(h.to_dict()))
        self.assertNotIn("state", h.to_dict())

    def test_a_revision_does_not_change_its_parents_decisions(self):
        first = self.make("first", EDITION, SPEC)
        self.decide(first, "accept")
        self.make("second", EDITION_2, SPEC_2, parent=first)
        h = history(self.source, "original.txt")
        self.assertEqual([d["decision"] for d in h.packets[first].decisions], ["accept"])
        self.assertEqual(h.packets["packets/second.packet.json"].decisions, [])

    def test_changed_original_is_a_problem_even_when_the_lineage_looks_valid(self):
        first = self.make("first", EDITION, SPEC)
        self.make("second", EDITION_2, SPEC_2, parent=first)
        self.write("original.txt", ORIGINAL + "A late entry.\n")
        h = history(self.source, "original.txt")
        self.assertFalse(h.ok)
        self.assertTrue(any("different bytes of the original" in p for p in h.problems))

    def test_missing_parent_is_a_problem(self):
        first = self.make("first", EDITION, SPEC)
        self.make("second", EDITION_2, SPEC_2, parent=first)
        (self.home / first).unlink()
        h = history(self.source, "original.txt")
        self.assertTrue(any("is missing" in p for p in h.problems), h.problems)
        self.assertIn("packets/second.packet.json", h.roots())  # still shown, not dropped

    def test_edited_parent_is_a_problem(self):
        first = self.make("first", EDITION, SPEC)
        self.make("second", EDITION_2, SPEC_2, parent=first)
        data = json.loads(self.source.read(first))
        data["changes"][0]["rationale"] = "rewritten after the fact"
        (self.home / first).write_text(json.dumps(data), encoding="utf-8")
        h = history(self.source, "original.txt")
        self.assertTrue(any("has changed since" in p for p in h.problems), h.problems)

    def test_parent_for_another_original_is_a_problem_in_history(self):
        self.write("other.txt", "A different log.\n")
        write_packet(build_packet(self.source, "other.txt", "other.txt", {"changes": [], "quotations": []}),
                     self.home / "packets", "other")
        first = self.make("first", EDITION, SPEC)
        data = json.loads(self.source.read(first))
        data["parent"] = {"name": "packets/other.packet.json", "sha256": "0" * 64}
        (self.home / first).write_text(json.dumps(data), encoding="utf-8")
        h = history(self.source, "original.txt")
        self.assertTrue(any("another original" in p for p in h.problems), h.problems)

    def test_cycle_is_a_problem(self):
        a = self.make("a", EDITION, SPEC)
        b = self.make("b", EDITION_2, SPEC_2, parent=a)
        data = json.loads(self.source.read(a))
        data["parent"] = {"name": b, "sha256": sha256(self.source.read(b))}
        (self.home / a).write_text(json.dumps(data), encoding="utf-8")
        h = history(self.source, "original.txt")
        self.assertTrue(any("loops back" in p for p in h.problems), h.problems)

    def test_corrupt_packet_and_log_line_are_reported_not_skipped(self):
        first = self.make("first", EDITION, SPEC)
        self.decide(first, "accept")
        (self.home / "packets" / "broken.packet.json").write_text("{not json", encoding="utf-8")
        with open(self.home / "decisions.jsonl", "a", encoding="utf-8") as handle:
            handle.write("{half a line\n")
        h = history(self.source, "original.txt")
        self.assertFalse(h.ok)
        self.assertTrue(any("broken.packet.json" in p for p in h.problems))
        self.assertTrue(any("line 2" in p for p in h.problems))
        self.assertEqual(len(h.events), 1)

    def test_decision_for_a_packet_that_is_gone_is_a_problem(self):
        first = self.make("first", EDITION, SPEC)
        self.decide(first, "accept")
        (self.home / first).unlink()
        (self.home / "packets" / "first.packet.md").unlink()
        h = history(self.source, "original.txt")
        self.assertTrue(any("isn't here" in p for p in h.problems), h.problems)

    def test_older_decision_lines_without_a_packet_are_marked_ambiguous_when_they_match_two(self):
        first = self.make("first", EDITION, SPEC)
        # Same edition text, built again as a revision: two packets, one edition hash.
        self.make("again", EDITION, SPEC, parent=first)
        record_decision(self.home, json.loads(self.source.read(first)), self.source, "accept", "zach")
        h = history(self.source, "original.txt")
        self.assertTrue(h.events[0].get("ambiguous"))
        self.assertEqual(len(h.events[0]["packets"]), 2)

    def test_other_originals_are_left_out(self):
        self.make("first", EDITION, SPEC)
        self.write("other.txt", "A different log.\n")
        write_packet(build_packet(self.source, "other.txt", "other.txt", {"changes": [], "quotations": []}),
                     self.home / "packets", "other")
        h = history(self.source, "original.txt")
        self.assertEqual(list(h.packets), ["packets/first.packet.json"])


class HistoryCommandLineTest(LineageTestCase):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--home", str(self.home), *args])
        return code, out.getvalue(), err.getvalue()

    def test_build_with_parent_decide_and_history(self):
        self.write("spec.json", json.dumps(SPEC))
        self.write("spec2.json", json.dumps(SPEC_2))
        self.write("edition2.txt", EDITION_2)
        self.assertEqual(self.run_cli("build", "original.txt", "edition.txt", "spec.json", "--stem", "one")[0], 0)
        code, out, err = self.run_cli("build", "original.txt", "edition2.txt", "spec2.json", "--stem", "two",
                                      "--parent", "packets/one.packet.json")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.run_cli("decide", "packets/two.packet.json", "accept", "--by", "zach")[0], 0)
        code, out, _ = self.run_cli("history", "original.txt")
        self.assertEqual(code, 0, out)
        self.assertIn("- packets/one.packet.json", out)
        self.assertIn("  - packets/two.packet.json", out)
        self.assertIn("accept by zach on packets/two.packet.json", out)

    def test_history_exits_1_on_a_problem_and_still_prints(self):
        self.make("first", EDITION, SPEC)
        self.write("original.txt", ORIGINAL + "A late entry.\n")
        code, out, _ = self.run_cli("history", "original.txt")
        self.assertEqual(code, 1)
        self.assertIn("Problems", out)

    def test_build_with_a_bad_parent_exits_1(self):
        self.write("spec.json", json.dumps(SPEC))
        self.write("notes.json", "[]")
        code, _, err = self.run_cli("build", "original.txt", "edition.txt", "spec.json", "--stem", "x",
                                    "--parent", "notes.json")
        self.assertEqual(code, 1)
        self.assertIn("not a packet", err)


class CodexReviewOn9Test(LineageTestCase):
    """Codex's three P2 findings on #9 (commit 58fdf78), each failing before its fix."""

    def test_older_decision_line_for_a_missing_packet_is_a_problem(self):
        first = self.make("first", EDITION, SPEC)
        record_decision(self.home, json.loads(self.source.read(first)), self.source, "accept", "zach")
        (self.home / first).unlink()
        h = history(self.source, "original.txt")
        self.assertFalse(h.ok)
        self.assertTrue(any("no packet here" in p for p in h.problems), h.problems)

    def test_malformed_nested_fields_are_reported_not_raised(self):
        self.make("first", EDITION, SPEC)
        for stem, data in (("e", {"original": {"name": "original.txt", "sha256": "x"}, "edition": None}),
                           ("o", {"original": None, "edition": {}}),
                           ("p", {"original": {"name": "original.txt", "sha256": sha256(ORIGINAL)},
                                  "edition": {"name": "e.txt", "sha256": "y"}, "parent": "packets/first.packet.json"}),
                           ("l", [1, 2])):
            (self.home / "packets" / f"{stem}.packet.json").write_text(json.dumps(data), encoding="utf-8")
        h = history(self.source, "original.txt")
        self.assertEqual(sum("unreadable packet" in p for p in h.problems), 4, h.problems)
        self.assertIn("packets/first.packet.json", h.packets)

    def test_equivalent_parent_spelling_links_to_the_same_packet(self):
        first = self.make("first", EDITION, SPEC)
        second = self.make("second", EDITION_2, SPEC_2, parent="./packets/../packets/first.packet.json")
        self.assertEqual(json.loads(self.source.read(second))["parent"]["name"], first)
        h = history(self.source, "original.txt")
        self.assertTrue(h.ok, h.problems)
        self.assertEqual(h.roots(), [first])

    def test_packet_written_with_an_unnormalised_parent_still_links(self):
        first = self.make("first", EDITION, SPEC)
        second = self.make("second", EDITION_2, SPEC_2, parent=first)
        data = json.loads(self.source.read(second))
        data["parent"]["name"] = "./" + first
        (self.home / second).write_text(json.dumps(data), encoding="utf-8")
        h = history(self.source, "original.txt")
        self.assertTrue(h.ok, h.problems)
        self.assertEqual(h.packets[first].children, [second])
        self.assertEqual(h.roots(), [first])
