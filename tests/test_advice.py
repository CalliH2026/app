import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from research import advice

COMMENT = "Des erreurs d'inattention en calcul, doit se relire."
GOOD = {"text": "Avant de rendre ta copie, refais chaque calcul de tête en le cachant : te tester ainsi fixe la méthode.",
        "source_name": "Dunlosky et al. (2013), Improving Students' Learning",
        "source_url": "https://journals.sagepub.com/doi/10.1177/1529100612453266"}


class FakeClient:
    def __init__(self, structured=GOOD, structured_error: Exception | None = None, answer=None) -> None:
        self.calls: list[dict] = []
        self.structured, self.structured_error, self.answer = structured, structured_error, answer

    def search(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["output_type"] == "structured":
            if self.structured_error:
                raise self.structured_error
            return dict(self.structured)
        if self.answer is None:
            raise RuntimeError("no answer")
        return SimpleNamespace(answer=self.answer, sources=[SimpleNamespace(name="", url=""),
                                                            SimpleNamespace(name="bad", url="ftp://eef.org.uk/x"),
                                                            SimpleNamespace(name="Education Endowment Foundation",
                                                                            url="https://eef.org.uk/metacognition")])


@pytest.fixture()
def cache(tmp_path: Path) -> Path:
    return tmp_path / "runs" / "advice-cache.jsonl"


def test_structured_query_and_result(cache):
    client = FakeClient()
    s = advice.suggest(COMMENT, client=client, cache_path=cache)
    assert s == advice.Suggestion(**GOOD)
    [call] = client.calls
    assert call["query"] == advice.build_query(COMMENT) and COMMENT in call["query"]
    assert call["depth"] == "standard" and call["output_type"] == "structured"
    schema = json.loads(call["structured_output_schema"])
    assert set(schema["required"]) == {"text", "source_name", "source_url"}
    for word in ("evidence-based", "attention", "retrieval practice", "French", "160"):
        assert word in call["query"]


def test_falls_back_to_sourced_answer_when_structured_is_unavailable(cache):
    client = FakeClient(structured_error=TypeError("unexpected keyword argument 'structured_output_schema'"),
                        answer="Fixe-toi un créneau court chaque soir pour revoir le cours de la veille.")
    s = advice.suggest(COMMENT, client=client, cache_path=cache)
    assert [c["output_type"] for c in client.calls] == ["structured", "sourcedAnswer"]
    assert s == advice.Suggestion(text="Fixe-toi un créneau court chaque soir pour revoir le cours de la veille.",
                                  source_name="Education Endowment Foundation",
                                  source_url="https://eef.org.uk/metacognition")


def test_missing_key_gives_no_suggestion_and_sends_nothing(cache, monkeypatch):
    monkeypatch.delenv("LINKUP_API_KEY", raising=False)
    monkeypatch.setattr(advice, "default_client", lambda: pytest.fail("no client without a key"))
    assert advice.suggest(COMMENT, cache_path=cache) is None
    assert not cache.exists()


def test_sentence_over_160_characters_is_rejected(cache):
    long = dict(GOOD, text="Relis " + "très " * 40 + "attentivement ta copie.")
    assert len(long["text"]) > 160
    assert advice.suggest(COMMENT, client=FakeClient(structured=long), cache_path=cache) is None


@pytest.mark.parametrize("text, url", [
    ("Relis ta copie. Puis refais les calculs.", GOOD["source_url"]),     # two sentences
    ("Check every result before handing in.", GOOD["source_url"]),       # not French
    ("Relis ta copie avant de la rendre", GOOD["source_url"]),           # no final punctuation
    ("", GOOD["source_url"]),
    (GOOD["text"], "javascript:alert(1)"),
    (GOOD["text"], ""),
])
def test_other_constraints(text, url):
    assert advice.validate(text, "x", url) is None


def test_cache_is_used_on_the_second_call(cache):
    client = FakeClient()
    first = advice.suggest(COMMENT, client=client, cache_path=cache)
    again = advice.suggest("  des erreurs d’inattention en calcul,  doit se relire ", client=client, cache_path=cache)
    assert first == again == advice.Suggestion(**GOOD)
    assert len(client.calls) == 1
    [line] = cache.read_text(encoding="utf-8").splitlines()
    assert json.loads(line)["key"] == advice.cache_key(COMMENT)


def test_a_failed_call_never_raises_and_is_not_cached(cache):
    client = FakeClient(structured_error=RuntimeError("timeout"))
    assert advice.suggest(COMMENT, client=client, cache_path=cache) is None
    assert advice.suggest(COMMENT, client=client, cache_path=cache) is None
    assert len(client.calls) == 4 and not cache.exists()


def test_student_names_are_replaced_before_sending(cache):
    client = FakeClient()
    advice.suggest("Lucas Bernard aide souvent Lucas et Petit-Jean; un petit effort reste à faire.", client=client,
                   cache_path=cache, names=["Lucas Bernard", "Lucas", "Bernard", "Petit"])
    query = client.calls[0]["query"]
    assert "Lucas" not in query and "Bernard" not in query
    assert "l'élève aide souvent l'élève et Petit-Jean; un petit effort" in query
    assert "Lucas" not in cache.read_text(encoding="utf-8")
