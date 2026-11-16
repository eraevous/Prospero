"""Tests for revision lineage and history (increment 2, HO-PRO-20261116-P8CB).

The acceptance checks come from Kate (API instance, 2026-11-16): immutable
lineage, fail closed on broken ancestry, keep branches without picking a
winner, keep recorded decisions apart from any derived state. All text is
invented for these tests (DEC-183, DEC-184).
"""

import io
import json
import os
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout

from prospero.packet import LineageError, RecordError, history, parent_ref, record_decision, render_history, write_packet
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
        self.assertFalse(h.ok)  # Kate's review: ambiguity is unresolved provenance
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

    def test_packets_folder_symlinked_inside_the_content_folder_still_links(self):
        # Codex review on #9 (b0cac1c): packets/ -> storage/ made the canonical
        # parent name differ from the listed packet name.
        (self.home / "storage").mkdir()
        try:
            os.symlink(self.home / "storage", self.home / "packets", target_is_directory=True)
        except (OSError, NotImplementedError) as error:  # e.g. Windows without privilege
            self.skipTest(f"symlinks unavailable: {error}")
        first = self.make("first", EDITION, SPEC)
        self.make("second", EDITION_2, SPEC_2, parent=first)
        h = history(self.source, "original.txt")
        self.assertTrue(h.ok, h.problems)
        self.assertEqual(len(h.packets), 2)
        self.assertEqual(len(h.roots()), 1)
        self.assertEqual(len(h.packets[h.roots()[0]].children), 1)


class KateReviewOn9Test(LineageTestCase):
    """Kate's (API instance) code review of #9, 2026-11-16: her fixtures, one test each."""

    def log(self, *entries):
        with open(self.home / "decisions.jsonl", "a", encoding="utf-8") as handle:
            for entry in entries:
                handle.write((entry if isinstance(entry, str) else json.dumps(entry)) + "\n")

    def test_packet_with_empty_original_and_edition_is_a_problem(self):
        (self.home / "packets").mkdir()
        (self.home / "packets" / "bad.packet.json").write_text('{"original": {}, "edition": {}}', encoding="utf-8")
        h = history(self.source, "original.txt")
        self.assertFalse(h.ok)
        self.assertTrue(any("bad.packet.json" in p for p in h.problems), h.problems)

    def test_list_original_and_list_parent_are_problems_not_crashes(self):
        first = self.make("first", EDITION, SPEC)
        (self.home / "packets" / "a.packet.json").write_text('{"original": [], "edition": {}}', encoding="utf-8")
        data = json.loads(self.source.read(first))
        data["parent"] = []
        (self.home / "packets" / "b.packet.json").write_text(json.dumps(data), encoding="utf-8")
        h = history(self.source, "original.txt")
        self.assertTrue(any("a.packet.json" in p for p in h.problems), h.problems)
        self.assertTrue(any("b.packet.json" in p for p in h.problems), h.problems)
        self.write("listy.json", json.dumps({"original": [], "edition": {}}))
        with self.assertRaises(LineageError):
            parent_ref(self.source, "listy.json", "original.txt")

    def test_decision_missing_its_fields_is_a_problem(self):
        self.log({"original": "original.txt"})
        h = history(self.source, "original.txt")
        self.assertFalse(h.ok)
        self.assertTrue(any("malformed decision" in p for p in h.problems), h.problems)
        self.assertEqual(h.events, [])

    def test_unknown_decision_word_is_a_problem(self):
        first = self.make("first", EDITION, SPEC)
        entry = self.decide(first, "accept")
        self.log(dict(entry, decision="maybe"))
        h = history(self.source, "original.txt")
        self.assertTrue(any("decision (accept" in p for p in h.problems), h.problems)

    def test_recorded_packet_name_must_match_as_well_as_the_hash(self):
        first = self.make("first", EDITION, SPEC)
        entry = self.decide(first, "accept")
        self.log(dict(entry, packet="packets/missing.packet.json"))
        h = history(self.source, "original.txt")
        self.assertFalse(h.ok)
        self.assertTrue(any("missing.packet.json" in p for p in h.problems), h.problems)
        self.assertEqual(len(h.packets[first].decisions), 1)  # only the honest line attaches

    def test_line_with_packet_name_but_no_hash_is_corrupt_not_legacy(self):
        first = self.make("first", EDITION, SPEC)
        entry = self.decide(first, "accept")
        broken = {k: v for k, v in entry.items() if k != "packet_sha256"}
        self.log(broken)
        h = history(self.source, "original.txt")
        self.assertTrue(any("packet and packet_sha256" in p for p in h.problems), h.problems)
        self.assertEqual(len(h.packets[first].decisions), 1)

    def test_unreadable_log_is_a_problem_not_an_empty_history(self):
        self.make("first", EDITION, SPEC)
        outside = Path(self._tmp.name) / "elsewhere.jsonl"
        outside.write_text("", encoding="utf-8")
        try:
            os.symlink(outside, self.home / "decisions.jsonl")
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"symlinks unavailable: {error}")
        h = history(self.source, "original.txt")
        self.assertFalse(h.ok)
        self.assertTrue(any("can't be read" in p for p in h.problems), h.problems)

    def test_absent_log_is_an_empty_history(self):
        self.make("first", EDITION, SPEC)
        h = history(self.source, "original.txt")
        self.assertTrue(h.ok, h.problems)
        self.assertEqual(h.events, [])

    def test_single_legacy_match_is_labelled_inferred(self):
        first = self.make("first", EDITION, SPEC)
        record_decision(self.home, json.loads(self.source.read(first)), self.source, "accept", "zach")
        h = history(self.source, "original.txt")
        self.assertTrue(h.ok, h.problems)
        self.assertEqual(h.events[0]["link"], "inferred")
        self.assertIn("(inferred", render_history(h))

    def test_packets_in_a_loop_are_still_listed(self):
        a = self.make("a", EDITION, SPEC)
        b = self.make("b", EDITION_2, SPEC_2, parent=a)
        data = json.loads(self.source.read(a))
        data["parent"] = {"name": b, "sha256": sha256(self.source.read(b))}
        (self.home / a).write_text(json.dumps(data), encoding="utf-8")
        text = render_history(history(self.source, "original.txt"))
        self.assertIn("broken lineage", text)
        self.assertIn(a, text)
        self.assertIn(b, text)


class CodexReviewOn831Test(LineageTestCase):
    """Codex's two P2 findings on #9 at 831e2ba."""

    def test_history_of_another_spelling_of_the_original_finds_its_packets(self):
        first = self.make("first", EDITION, SPEC)
        self.decide(first, "accept")
        h = history(self.source, "./original.txt")
        self.assertEqual(list(h.packets), [first])
        self.assertEqual(len(h.events), 1)
        self.write("original.txt", ORIGINAL + "A late entry.\n")
        self.assertFalse(history(self.source, "./original.txt").ok)

    def test_records_written_with_another_spelling_still_count(self):
        self.write("edition.txt", EDITION)
        packet = build_packet(self.source, "./original.txt", "edition.txt", SPEC)
        write_packet(packet, self.home / "packets", "dotted")
        self.assertEqual(list(history(self.source, "original.txt").packets), ["packets/dotted.packet.json"])
        ref = parent_ref(self.source, "packets/dotted.packet.json", "original.txt")
        self.assertEqual(ref["name"], "packets/dotted.packet.json")

    def test_cli_build_stores_the_canonical_original(self):
        self.write("spec.json", json.dumps(SPEC))
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            main(["--home", str(self.home), "build", "./original.txt", "edition.txt", "spec.json", "--stem", "c"])
        self.assertEqual(json.loads(self.source.read("packets/c.packet.json"))["original"]["name"], "original.txt")

    def test_packet_that_cannot_be_opened_is_reported(self):
        first = self.make("first", EDITION, SPEC)
        self.make("second", EDITION_2, SPEC_2, parent=first)
        real_read = self.source.read

        def read(name):
            if name.endswith("second.packet.json"):
                raise PermissionError(13, "Permission denied", name)
            return real_read(name)

        self.source.read = read
        h = history(self.source, "original.txt")
        self.assertFalse(h.ok)
        self.assertTrue(any("second.packet.json" in p and "unreadable" in p for p in h.problems), h.problems)
        self.assertIn(first, h.packets)


class KateRound3Test(LineageTestCase):
    """Kate's round-3 review on #9: a recorded decision must agree with its packet."""

    def test_decision_whose_metadata_contradicts_its_packet_is_a_problem(self):
        first = self.make("first", EDITION, SPEC)
        entry = self.decide(first, "accept")
        with open(self.home / "decisions.jsonl", "a", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(entry, original_sha256="wrong-original-hash", edition="wrong-edition.txt",
                                         edition_sha256="wrong-edition-hash")) + "\n")
        h = history(self.source, "original.txt")
        self.assertFalse(h.ok)
        self.assertTrue(any("contradict" in p and "edition_sha256" in p for p in h.problems), h.problems)

    def test_consistent_decision_stays_ok(self):
        first = self.make("first", EDITION, SPEC)
        self.decide(first, "accept")
        self.assertTrue(history(self.source, "original.txt").ok)


class CodexReviewOn847Test(LineageTestCase):
    """Codex's two P2 findings on #9 at 847a827."""

    def test_non_boolean_ok_is_a_corrupt_packet_not_a_crash(self):
        first = self.make("first", EDITION, SPEC)
        for stem, value in (("l", []), ("d", {})):
            data = json.loads(self.source.read(first))
            data["ok"] = value
            (self.home / "packets" / f"{stem}.packet.json").write_text(json.dumps(data), encoding="utf-8")
        h = history(self.source, "original.txt")
        self.assertEqual(sum("unreadable packet" in p for p in h.problems), 2, h.problems)
        render_history(h)  # must not raise

    def test_dangling_packet_link_is_reported(self):
        (self.home / "packets").mkdir()
        try:
            os.symlink(Path(self._tmp.name) / "gone.json", self.home / "packets" / "first.packet.json")
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"symlinks unavailable: {error}")
        h = history(self.source, "original.txt")
        self.assertFalse(h.ok)
        self.assertTrue(any("first.packet.json" in p for p in h.problems), h.problems)

    def test_packet_link_out_of_the_folder_is_reported_not_read(self):
        outside = Path(self._tmp.name) / "outside.packet.json"
        outside.write_text("{}", encoding="utf-8")
        (self.home / "packets").mkdir()
        try:
            os.symlink(outside, self.home / "packets" / "out.packet.json")
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"symlinks unavailable: {error}")
        h = history(self.source, "original.txt")
        self.assertTrue(any("out.packet.json" in p and "outside" in p for p in h.problems), h.problems)


class CopilotReviewOn9Test(LineageTestCase):
    """Copilot's five findings on #9 at fe16c32."""

    def test_unicode_line_separator_in_a_note_stays_one_record(self):
        first = self.make("first", EDITION, SPEC)
        text = self.source.read(first)
        record_decision(self.home, json.loads(text), self.source, "accept", "zach", note="one two",
                        packet_name=first, packet_sha256=sha256(text))
        h = history(self.source, "original.txt")
        self.assertTrue(h.ok, h.problems)
        self.assertEqual(h.events[0]["note"], "one two")

    def test_malformed_line_naming_another_original_is_still_a_problem(self):
        self.make("first", EDITION, SPEC)
        with open(self.home / "decisions.jsonl", "a", encoding="utf-8") as handle:
            handle.write('{"original": ""}\n')
        h = history(self.source, "original.txt")
        self.assertFalse(h.ok)
        self.assertTrue(any("malformed decision" in p for p in h.problems), h.problems)

    def test_recorder_refuses_half_a_packet_reference(self):
        first = self.make("first", EDITION, SPEC)
        packet = json.loads(self.source.read(first))
        for kwargs in ({"packet_name": first}, {"packet_sha256": "a" * 64}):
            with self.assertRaises(RecordError, msg=kwargs):
                record_decision(self.home, packet, self.source, "accept", "zach", **kwargs)
        self.assertFalse((self.home / "decisions.jsonl").exists())

    def test_packets_that_is_a_file_is_a_problem(self):
        (self.home / "packets").write_text("not a folder", encoding="utf-8")
        h = history(self.source, "original.txt")
        self.assertFalse(h.ok)
        self.assertTrue(any("not a folder" in p for p in h.problems), h.problems)

    def test_packets_dangling_link_is_a_problem(self):
        try:
            os.symlink(Path(self._tmp.name) / "gone", self.home / "packets", target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"symlinks unavailable: {error}")
        h = history(self.source, "original.txt")
        self.assertFalse(h.ok, h.problems)

    def test_packets_linked_outside_is_refused_before_listing(self):
        outside = Path(self._tmp.name) / "elsewhere"
        outside.mkdir()
        (outside / "secret-name.packet.json").write_text("{}", encoding="utf-8")
        try:
            os.symlink(outside, self.home / "packets", target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"symlinks unavailable: {error}")
        h = history(self.source, "original.txt")
        self.assertFalse(h.ok)
        self.assertTrue(any("outside the source folder" in p for p in h.problems), h.problems)
        self.assertFalse(any("secret-name" in p for p in h.problems), h.problems)


class CodexReviewOn479Test(LineageTestCase):
    """Codex's finding on #9 at 47963a4: symlink loops are reported, not raised."""

    def loop(self, link):
        try:
            os.symlink(link, link)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"symlinks unavailable: {error}")

    def test_looping_packets_folder_is_a_problem(self):
        self.loop(self.home / "packets")
        h = history(self.source, "original.txt")
        self.assertFalse(h.ok)
        self.assertTrue(any(p.startswith("packets/") for p in h.problems), h.problems)

    def test_looping_packet_file_is_a_problem(self):
        self.make("first", EDITION, SPEC)
        self.loop(self.home / "packets" / "loop.packet.json")
        h = history(self.source, "original.txt")
        self.assertFalse(h.ok)
        self.assertTrue(any("loop.packet.json" in p for p in h.problems), h.problems)


class CopilotReviewOnA8eTest(LineageTestCase):
    """Copilot's three "previously missed" findings on #9 at a8efb67."""

    def rewrite_packet(self, name, change):
        data = json.loads(self.source.read(name))
        change(data)
        (self.home / name).write_text(json.dumps(data), encoding="utf-8")

    def test_packet_with_an_empty_original_name_is_a_problem(self):
        first = self.make("first", EDITION, SPEC)
        self.rewrite_packet(first, lambda d: d["original"].update(name=""))
        h = history(self.source, "original.txt")
        self.assertFalse(h.ok)
        self.assertTrue(any("first.packet.json" in p for p in h.problems), h.problems)

    def test_packet_names_with_nul_are_problems_not_crashes(self):
        for part in ("original", "edition", "parent"):
            with self.subTest(part=part):
                first = self.make(f"{part}-first", EDITION, SPEC)
                second = self.make(f"{part}-second", EDITION_2, SPEC_2, parent=first)
                target = first if part != "parent" else second
                self.rewrite_packet(target, lambda d: d[part].update(name="bad\x00name"))
                h = history(self.source, "original.txt")
                self.assertFalse(h.ok)
                stem = target.rsplit("/", 1)[1]
                self.assertTrue(any(stem in p and "unreadable packet" in p for p in h.problems), h.problems)

    def test_decision_paths_with_nul_are_reported_not_raised(self):
        first = self.make("first", EDITION, SPEC)
        self.decide(first, "accept")
        good = json.loads((self.home / "decisions.jsonl").read_text(encoding="utf-8"))
        for field in ("original", "packet"):
            with self.subTest(field=field):
                bad = dict(good, **{field: "bad\x00name"})
                with open(self.home / "decisions.jsonl", "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(bad) + "\n")
                h = history(self.source, "original.txt")
                self.assertFalse(h.ok)
                self.assertTrue(any("malformed decision" in p for p in h.problems), h.problems)
                # The well-formed line is still read.
                self.assertTrue(any(e.get("decision") == "accept" for e in h.events), h.events)

    def test_unlistable_packets_folder_is_a_problem(self):
        from unittest import mock
        self.make("first", EDITION, SPEC)
        packets = (self.home / "packets").resolve()
        real_scandir = os.scandir

        def refuse(path=".", *args, **kwargs):
            if Path(os.fsdecode(path)).resolve() == packets:
                raise PermissionError(13, "Permission denied", str(path))
            return real_scandir(path, *args, **kwargs)

        with mock.patch("os.scandir", side_effect=refuse), mock.patch("os.listdir", side_effect=refuse):
            h = history(self.source, "original.txt")
        self.assertFalse(h.ok)
        self.assertTrue(any(p.startswith("packets/") and "can't be listed" in p for p in h.problems), h.problems)
