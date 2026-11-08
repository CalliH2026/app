import datetime as dt
from pathlib import Path
from types import SimpleNamespace

from research import target_notes

ANSWER = """Dans PRONOTE, la saisie se fait ainsi :
1. Affichez Bulletins > Saisie des appréciations > Saisie des appréciations des professeurs par matière.
2. Sélectionnez la classe et le service, puis la période dans la liste déroulante.
3. Double-cliquez dans la cellule « Appréciations » de l'élève,
   saisissez le texte puis validez avec Entrée.
4. La saisie est enregistrée automatiquement, sans message de confirmation."""


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(answer=ANSWER, sources=[
            SimpleNamespace(name="Index Éducation - Saisir les appréciations", url="https://www.index-education.com/fr/a",
                            snippet="..."),
            SimpleNamespace(name="duplicate", url="https://www.index-education.com/fr/a", snippet="..."),
            SimpleNamespace(name="", url="https://www.index-education.com/fr/b", snippet="..."),
        ])


def test_query_asks_for_click_path_field_names_and_save_behaviour():
    q = target_notes.build_query("PRONOTE", "saisie des appréciations par matière")
    assert "PRONOTE" in q and "saisie des appréciations par matière" in q
    assert "official documentation" in q
    assert "click path" in q and "exactly as displayed" in q
    assert "confirmation" in q and "autosave" in q and "validation" in q


def test_draft_markdown_from_a_fixed_answer():
    client = FakeClient()
    md = target_notes.draft("PRONOTE", "saisie des appréciations par matière", client, today=dt.date(2026, 11, 7))
    assert client.calls == [{"query": target_notes.build_query("PRONOTE", "saisie des appréciations par matière"),
                             "depth": "deep", "output_type": "sourcedAnswer"}]
    lines = md.splitlines()
    assert lines[0] == "# PRONOTE: saisie des appréciations par matière"
    assert "> **Draft from official documentation, not yet verified against the application.**" in lines
    assert "1. Dans PRONOTE, la saisie se fait ainsi :" in lines
    assert "2. Affichez Bulletins > Saisie des appréciations > Saisie des appréciations des professeurs par matière." in lines
    assert ("4. Double-cliquez dans la cellule « Appréciations » de l'élève, saisissez le texte puis validez avec Entrée."
            in lines)
    assert "5. La saisie est enregistrée automatiquement, sans message de confirmation." in lines
    sources = lines[lines.index("## Sources") + 2:]
    assert sources[0] == "- Index Éducation - Saisir les appréciations: <https://www.index-education.com/fr/a>"
    assert sources[1] == "- https://www.index-education.com/fr/b: <https://www.index-education.com/fr/b>"
    assert sources[2] == ""
    assert "Drafted on 2026-11-07" in md


def test_plain_paragraph_answer_is_numbered_by_sentence():
    assert target_notes.as_procedure("Ouvrez la page. Cliquez sur Enregistrer.") == ["Ouvrez la page.",
                                                                                   "Cliquez sur Enregistrer."]


def test_main_writes_the_draft(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("LINKUP_API_KEY", raising=False)
    out = tmp_path / "targets" / "pronote.draft.md"
    rc = target_notes.main(["--app", "PRONOTE", "--task", "saisie", "--out", str(out)], client=FakeClient())
    assert rc == 0
    assert out.read_text(encoding="utf-8").startswith("# PRONOTE: saisie\n")


def test_main_without_key_sends_nothing(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.delenv("LINKUP_API_KEY", raising=False)
    out = tmp_path / "draft.md"
    assert target_notes.main(["--app", "PRONOTE", "--task", "saisie", "--out", str(out)]) == 2
    assert not out.exists()
    assert "LINKUP_API_KEY is not set" in capsys.readouterr().err
