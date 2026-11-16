"""Adversarial cases for the packet checks: a regression gate.

Kate (API instance) listed these on 2026-11-15 as edits that might slip past
the checks, and asked on 2026-11-16 that they become a gate with *intended*
outcomes, not just tests that run. Each test says what should happen and why.
Where a case is outside what the checks claim to detect, the test is named
``test_known_limit_…`` and pins the current behaviour so a change to it is
noticed; the limit is also written in the README. All text is invented.
"""

from test_packet import ORIGINAL, SPEC, PacketTestCase


def spec_with(*changes, quotations=None):
    return {"changes": list(SPEC["changes"]) + list(changes),
            "quotations": SPEC["quotations"] if quotations is None else quotations}


class AdversarialGateTest(PacketTestCase):
    base = (
        "The lamp went dark at nine.\n"
        "Marta said \"the oil was thin this winter.\"\n"
        "We relit it by hand and kept watch until dawn.\n"
        "Nobody slept.\n"
    )

    def labelled_ok(self, edition, spec=SPEC):
        return self.check(self.build(spec, edition=edition), "changes-labelled").ok

    def test_punctuation_only_edit_must_be_labelled(self):
        # "dawn." -> "dawn!" changes no letters, but it changes the text.
        self.assertFalse(self.labelled_ok(self.base.replace("until dawn.", "until dawn!")))

    def test_labelled_punctuation_edit_passes(self):
        spec = spec_with({"id": "p", "kind": "transformation", "rationale": "more urgent",
                          "original_text": "dawn.", "edition_text": "dawn!"})
        self.assertTrue(self.labelled_ok(self.base.replace("until dawn.", "until dawn!"), spec))

    def test_reordering_words_must_be_labelled(self):
        self.assertFalse(self.labelled_ok(self.base.replace("by hand and kept watch", "and kept watch by hand")))

    def test_label_on_an_earlier_repeat_of_a_word_does_not_cover_a_later_change(self):
        # The edition changes the second "it" to "the lamp"; the label's
        # edition_text "the lamp" is first found on line 1, which is unchanged.
        edition = self.base.replace("We relit it by hand", "We relit the lamp by hand")
        spec = spec_with({"id": "r", "kind": "transformation", "rationale": "clearer referent",
                          "original_text": "it", "edition_text": "the lamp"})
        self.assertFalse(self.labelled_ok(edition, spec))

    def test_repeat_label_with_enough_context_passes(self):
        edition = self.base.replace("We relit it by hand", "We relit the lamp by hand")
        spec = spec_with({"id": "r", "kind": "transformation", "rationale": "clearer referent",
                          "original_text": "relit it by", "edition_text": "relit the lamp by"})
        self.assertTrue(self.labelled_ok(edition, spec))

    def test_interpretation_partly_overlapping_a_quotation_fails(self):
        # The interpretation starts outside the quotation marks and runs into them.
        edition = self.base.replace("Marta said \"the oil", "Marta, worried, said \"the oil")
        spec = spec_with({"id": "i", "kind": "interpretation", "rationale": "reads her tone",
                          "edition_text": "worried, said \"the oil"})
        self.assertFalse(self.check(self.build(spec, edition=edition), "no-interpretation-as-quotation").ok)

    def test_interpretation_without_edition_text_cannot_hide_inside_a_quotation(self):
        # An interpretation that names only original_text adds nothing to the
        # edition, so it can't sit inside quotation marks. Any words that do
        # appear inside the marks must still be the source's, verbatim.
        edition = self.base.replace("\"the oil was thin this winter.\"", "\"the oil was thin and she was afraid.\"")
        spec = spec_with({"id": "i", "kind": "interpretation", "rationale": "reads her tone",
                          "original_text": "this winter."},
                         quotations=[{"text": "the oil was thin and she was afraid.", "source": "original"}])
        packet = self.build(spec, edition=edition)
        self.assertFalse(self.check(packet, "quotations-resolve").ok)

    def test_undeclared_text_in_curly_quotes_fails(self):
        edition = self.base.replace("Nobody slept.", "“Nobody slept,” Marta said.")
        self.assertFalse(self.check(self.build(SPEC, edition=edition), "quotations-resolve").ok)

    def test_known_limit_single_quotes_are_not_treated_as_quotation(self):
        # Single quotes aren't read as quotation marks (apostrophes make them
        # ambiguous), so an interpretation inside them isn't caught by
        # no-interpretation-as-quotation. The words still count as a change
        # and must be labelled; what isn't checked is the attribution.
        edition = self.base.replace("Nobody slept.", "Marta said 'we are afraid'.")
        spec = {"changes": [SPEC["changes"][0],
                            {"id": "i", "kind": "interpretation", "rationale": "reads her tone",
                             "edition_text": "Marta said 'we are afraid'."}],
                "quotations": SPEC["quotations"]}
        packet = self.build(spec, edition=edition)
        self.assertTrue(self.check(packet, "no-interpretation-as-quotation").ok)

    def test_known_limit_reported_speech_without_marks_is_not_an_attribution(self):
        # "Marta thought the keeper was lazy" attributes a view without quotation
        # marks. The checks only see that it is a labelled change; whether the
        # attribution is fair is the reader's call.
        edition = self.base.replace("Nobody slept.", "Marta thought the keeper was lazy.")
        spec = {"changes": [SPEC["changes"][0],
                            {"id": "c2", "kind": "interpretation", "rationale": "reads her mood",
                             "edition_text": "Marta thought the keeper was lazy."}],
                "quotations": SPEC["quotations"]}
        packet = self.build(spec, edition=edition)
        self.assertTrue(packet.ok, [c.problems for c in packet.checks])

    def test_original_is_never_modified_by_any_case(self):
        self.build(SPEC, edition=self.base.replace("dawn.", "dawn!"))
        self.assertEqual((self.home / "original.txt").read_text(encoding="utf-8"), ORIGINAL)
