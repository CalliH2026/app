from pathlib import Path

import pytest

from voice.gladia_live import Utterance
from voice.roster import load_roster, normalize, phonetic
from voice.structurer import AMBIGUOUS_CONFIDENCE, Drafts, LLMStructurer, RuleBasedStructurer

ROSTER = Path(__file__).parent / "fixtures" / "roster.csv"


@pytest.fixture(scope="module")
def s() -> RuleBasedStructurer:
    return RuleBasedStructurer(load_roster(ROSTER))


def one(s: RuleBasedStructurer, text: str):
    items = s.structure(text)
    assert len(items) == 1, items
    return items[0]


def test_roster_aliases_and_normalization():
    roster = {st.student_id: st for st in load_roster(ROSTER)}
    assert roster["s05"].aliases == ("Max",)
    assert normalize("Maëlle  ROUX !") == "maelle roux"
    assert phonetic("Maëlle") == phonetic("Maël")
    assert phonetic("Inesse") == phonetic("Inès")


def test_two_identical_first_names_return_both_below_half(s):
    item = one(s, "Léa, très bon trimestre.")
    assert item.kind == "comment"
    assert sorted(item.student_candidates) == ["s01", "s02"]
    assert item.confidence < 0.5
    assert item.text == "Très bon trimestre."


def test_full_name_disambiguates_identical_first_names(s):
    item = one(s, "Léa Bernard : très bon trimestre.")
    assert item.student_candidates == ["s02"]
    assert item.confidence >= 0.9


def test_accent_and_case_insensitive(s):
    item = one(s, "lea MARTIN participe bien")
    assert item.student_candidates == ["s01"]
    assert item.text == "Participe bien"


def test_homophone_first_names_are_ambiguous(s):
    # Maël and Maëlle sound the same: the transcript spelling cannot be trusted, the UI asks
    item = one(s, "Pour Maëlle, des progrès à l'oral.")
    assert sorted(item.student_candidates) == ["s03", "s04"]
    assert item.confidence == AMBIGUOUS_CONFIDENCE


def test_homophone_resolved_by_last_name(s):
    item = one(s, "Maëlle Dupont, des progrès à l'oral.")
    assert item.student_candidates == ["s03"]


def test_homophone_misspelling_from_stt(s):
    item = one(s, "Inesse Moreau, bon trimestre.")
    assert item.student_candidates == ["s06"]
    assert item.confidence >= 0.9


def test_nickname(s):
    assert one(s, "Max, travail irrégulier.").student_candidates == ["s05"]
    assert one(s, "Coco participe bien.").student_candidates == ["s09"]


def test_mid_sentence_correction_keeps_only_the_corrected_text(s):
    item = one(s, "Hugo Lefèvre, travail sérieux, non plutôt, travail irrégulier ce trimestre.")
    assert item.kind == "comment"
    assert item.student_candidates == ["s07"]
    assert item.text == "Travail irrégulier ce trimestre."


def test_mid_sentence_correction_of_the_name(s):
    item = one(s, "Hugo Lefèvre, non plutôt Théo Fontaine, bavarde trop.")
    assert item.student_candidates == ["s10"]
    assert item.text == "Bavarde trop."


def test_correction_text_for_previous_item(s):
    item = one(s, "Non, plutôt : participe activement.")
    assert item.kind == "correction_text"
    assert item.text == "Participe activement."
    assert item.student_candidates == []


def test_reassign(s):
    item = one(s, "Non, cette remarque était pour Zoé.")
    assert item.kind == "reassign"
    assert item.student_candidates == ["s08"]
    assert item.text == ""


def test_reassign_to_ambiguous_name_asks(s):
    item = one(s, "Non, cette remarque était pour Léa.")
    assert item.kind == "reassign"
    assert sorted(item.student_candidates) == ["s01", "s02"]
    assert item.confidence < 0.5


def test_undo_and_stop(s):
    assert one(s, "Annule la dernière.").kind == "undo"
    assert one(s, "Euh, annule la dernière").kind == "undo"
    assert one(s, "Stop.").kind == "stop"
    assert one(s, "Arrête !").kind == "stop"


def test_fillers_produce_nothing(s):
    assert s.structure("euh") == []
    assert s.structure("") == []


def test_no_name_gives_low_confidence_comment(s):
    item = one(s, "Très bon trimestre.")
    assert item.student_candidates == [] and item.confidence < 0.5


def test_two_students_in_one_utterance(s):
    items = s.structure("Théo, bon trimestre. Zoé Garnier, des efforts à poursuivre.")
    assert [(i.student_candidates, i.text) for i in items] == [
        (["s10"], "Bon trimestre."),
        (["s08"], "Des efforts à poursuivre."),
    ]


def test_stt_confidence_caps_item_confidence(s):
    item = one(s, Utterance("Max, travail irrégulier.", 0.0, 2.0, 0.55))
    assert item.confidence == 0.55


def test_text_is_never_invented(s):
    utterances = ["Léa, très bon trimestre.", "Hugo Lefèvre, travail sérieux, non plutôt, travail irrégulier.",
                  "Coco participe bien.", "Théo, bon trimestre. Zoé Garnier, des efforts à poursuivre."]
    for u in utterances:
        for item in s.structure(u):
            assert normalize(item.text) in normalize(u)


def test_demo_stream_end_to_end(s):
    """A fake utterance stream covering the demo: corrections apply to the last draft, reassign moves it."""
    stream = [
        Utterance("Léa Martin, participe bien, doit soigner la rédaction.", 0.0, 3.1, 0.93),
        Utterance("Max, trimestre sérieux.", 4.0, 5.5, 0.91),
        Utterance("Non, plutôt : trimestre sérieux, continue ainsi.", 6.0, 8.0, 0.92),
        Utterance("Pour Maëlle, des progrès nets à l'oral.", 9.0, 11.0, 0.9),
        Utterance("Non, cette remarque était pour Zoé.", 12.0, 13.5, 0.94),
        Utterance("Inesse Moreau, travail irrégulier.", 14.0, 15.5, 0.9),
        Utterance("Annule la dernière.", 16.0, 17.0, 0.97),
        Utterance("Léa, bonne participation.", 18.0, 19.5, 0.92),
        Utterance("Stop.", 20.0, 20.5, 0.99),
    ]
    drafts = Drafts()
    actions = [drafts.apply(item) for u in stream for item in s.structure(u)]
    assert actions == ["added", "added", "text_replaced", "added", "reassigned", "added", "removed_draft",
                       "added", "stopped"]
    assert [(d.student_candidates, d.text) for d in drafts.items] == [
        (["s01"], "Participe bien, doit soigner la rédaction."),
        (["s05"], "Trimestre sérieux, continue ainsi."),
        (["s08"], "Des progrès nets à l'oral."),  # moved, not duplicated
        (["s01", "s02"], "Bonne participation."),
    ]
    assert drafts.items[-1].confidence < 0.5
    assert drafts.stopped


def test_undo_with_no_draft_goes_to_the_journal(s):
    drafts = Drafts()
    assert drafts.apply(one(s, "Annule la dernière.")) == "undo_write"


def test_llm_structurer_is_a_stub_without_completion():
    roster = load_roster(ROSTER)
    with pytest.raises(NotImplementedError):
        LLMStructurer(roster).structure("Léa, bon trimestre.")


def test_llm_structurer_validates_injected_output():
    roster = load_roster(ROSTER)
    prompts: list[str] = []

    def fake_complete(prompt: str) -> str:
        prompts.append(prompt)
        return ('[{"student_candidates": ["s01", "s02"], "text": "bon trimestre", "confidence": 0.9,'
                ' "kind": "comment"},'
                ' {"student_candidates": ["s99"], "text": "invented words", "confidence": 0.9, "kind": "comment"},'
                ' {"student_candidates": [], "text": "", "confidence": 0.9, "kind": "launch"}]')

    items = LLMStructurer(roster, fake_complete).structure("Léa, bon trimestre.")
    assert len(items) == 1
    assert items[0].student_candidates == ["s01", "s02"] and items[0].confidence < 0.5
    assert "s05: Maximilien Petit" in prompts[0] and "Max" in prompts[0]
