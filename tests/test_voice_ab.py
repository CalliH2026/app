import json
from pathlib import Path

from voice.ab import main, read_transcript, score_arm
from voice.roster import load_roster

ROSTER = Path(__file__).parent / "fixtures" / "roster.csv"


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_ab_scores_both_arms(tmp_path, capsys):
    truth = write(tmp_path / "truth.csv", "item_id,student_id,text\n"
                  "v01,s01,Participe bien.\n"
                  "v02,s05,Travail irrégulier.\n"
                  "v03,s06,Bon trimestre.\n"
                  "v04,s04,Des progrès.\n")
    with_vocab = write(tmp_path / "with.csv", "item_id,text,start,end,confidence\n"
                       "v01,\"Léa Martin, participe bien.\",0.1,2.0,0.9\n"
                       "v02,\"Max, travail irrégulier.\",0.1,2.0,0.9\n"
                       "v03,\"Inès Moreau,\",0.1,1.0,0.9\n"
                       "v03,\"bon trimestre.\",1.2,2.0,0.9\n"
                       "v04,\"Maëlle, des progrès.\",0.1,2.0,0.9\n")
    without_vocab = write(tmp_path / "without.csv", "item_id,text,start,end,confidence\n"
                          "v01,\"Léa Martin, participe bien.\",0.1,2.0,0.9\n"
                          "v02,\"Mac, travail irrégulier.\",0.1,2.0,0.9\n"
                          "v04,\"Mais elle, des progrès.\",0.1,2.0,0.9\n")
    out_json = tmp_path / "ab.json"
    assert main(["--truth", str(truth), "--with-vocab", str(with_vocab), "--without-vocab", str(without_vocab),
                 "--roster", str(ROSTER), "--json", str(out_json)]) == 0
    table = capsys.readouterr().out
    assert "| with vocabulary | 4 | 3 | 1 | 0 | 0 | 3/4 (75%) | 4/4 |" in table
    assert "| without vocabulary | 4 | 1 | 0 | 2 | 1 | 1/4 (25%) | 1/4 |" in table
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload[0]["accuracy"] == 0.75
    assert payload[1]["per_item"][2] == {"item_id": "v03", "expected": "s06", "candidates": [],
                                         "outcome": "missing", "transcript": None}


def test_transcript_rows_are_joined_in_time_order(tmp_path):
    t = write(tmp_path / "t.csv", "item_id,text,start,end,confidence\n"
              "a,bon trimestre.,1.5,2,0.9\n"
              "a,\"Zoé,\",0.1,1,0.9\n")
    assert read_transcript(t) == {"a": "Zoé, bon trimestre."}
    res = score_arm("x", [{"item_id": "a", "student_id": "s08"}], read_transcript(t), load_roster(ROSTER))
    assert res.correct == 1
