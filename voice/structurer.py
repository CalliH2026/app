"""Turn one final utterance into zero or more candidate items for the approval UI.

Each item is `{student_candidates, text, confidence, kind}` with kind one of:

- `comment`: a new appreciation for the named student ("Léa Martin, participe bien.")
- `correction_text`: replaces the text of the previous item ("Non, plutôt : participe activement.")
- `reassign`: moves the previous item to another student ("Non, cette remarque était pour Léa.")
- `undo`: "annule la dernière"
- `stop`: "stop", "arrête"

Rule-based: names come from the roster (display names and aliases), matched accent- and
case-insensitively with a fuzzy and a rough phonetic score. When several students match
equally, all are returned with confidence below 0.5 so the UI asks. The text is always a span
of what the teacher said, never generated.

`LLMStructurer` is the pluggable alternative: same interface, the completion function is
injected, no network call is made from this module.
"""

from __future__ import annotations

import difflib
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Protocol

from voice.gladia_live import Utterance
from voice.roster import Student, normalize, phonetic, strip_accents

KINDS = ("comment", "correction_text", "reassign", "undo", "stop")

MATCH_THRESHOLD = 0.84
TIE_MARGIN = 0.05
AMBIGUOUS_CONFIDENCE = 0.4
NO_STUDENT_CONFIDENCE = 0.2

_FILLERS = {"euh", "alors", "donc", "bon", "ensuite", "et", "maintenant", "puis", "ok", "bien", "voila"}
_NAME_INTRO = {"pour", "appreciation", "de", "d", "concernant", "eleve"}
_STOP_WORDS = {"stop", "stoppe", "arrete", "arretez", "arreter", "pause"}
_UNDO_WORDS = {"annule", "annuler", "annulez", "efface", "effacer", "supprime", "supprimer"}
_CORRECTION_MARKERS = [("non", "plutot"), ("pardon", "plutot"), ("enfin", "plutot"), ("non", "pardon")]
_REASSIGN_LEAD = {"non", "pardon", "oups", "erreur"}

_TOKEN = re.compile(r"\w+", re.UNICODE)
_SENTENCE_END = re.compile(r"[.;!?]+\s*")


@dataclass
class CandidateItem:
    student_candidates: list[str]
    text: str
    confidence: float
    kind: str

    def to_dict(self) -> dict:
        return asdict(self)


class Structurer(Protocol):
    def structure(self, utterance: Utterance | str) -> list[CandidateItem]: ...


@dataclass(frozen=True)
class _Tok:
    norm: str
    start: int
    end: int


def _tokens(text: str, offset: int = 0) -> list[_Tok]:
    return [_Tok(strip_accents(m.group()).lower(), m.start() + offset, m.end() + offset) for m in _TOKEN.finditer(text)]


def _ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


@dataclass(frozen=True)
class _Form:
    student_id: str
    norm: str
    phon: str
    n_tokens: int


@dataclass
class NameMatch:
    student_ids: list[str]
    confidence: float
    end: int  # token index just after the name
    score: float = 0.0
    n_tokens: int = 0
    runner_up: float = 0.0
    tied: list[str] = field(default_factory=list)


class RuleBasedStructurer:
    def __init__(self, students: list[Student]):
        self.students = students
        self._forms = [
            _Form(s.student_id, normalize(f), phonetic(f), len(normalize(f).split()))
            for s in students
            for f in s.name_forms()
        ]
        self._max_tokens = max((f.n_tokens for f in self._forms), default=1)

    # ---- name matching -------------------------------------------------

    def _form_score(self, form: _Form, window: list[_Tok]) -> float:
        norm = " ".join(t.norm for t in window)
        if norm == form.norm:
            return 1.0
        phon = phonetic(norm)
        if phon == form.phon:
            return 1.0
        if len(form.norm) <= 3 or len(norm) <= 3:
            return 0.0  # short names ("Max", "Léo") match exactly or phonetically only
        return max(_ratio(norm, form.norm), _ratio(phon, form.phon))

    def match_at(self, toks: list[_Tok], i: int) -> NameMatch | None:
        """Best roster match for a name starting at token `i`, or None."""
        best: dict[str, tuple[int, float]] = {}
        for form in self._forms:
            if i + form.n_tokens > len(toks):
                continue
            score = self._form_score(form, toks[i : i + form.n_tokens])
            if score < MATCH_THRESHOLD:
                continue
            key = (form.n_tokens, score)
            if form.student_id not in best or key > best[form.student_id]:
                best[form.student_id] = key
        if not best:
            return None
        ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)
        top_n, top_score = ranked[0][1]
        tied = [sid for sid, (n, s) in ranked if n == top_n and s >= top_score - TIE_MARGIN]
        others = [s for sid, (n, s) in ranked if sid not in tied and n == top_n]
        runner_up = max(others, default=0.0)
        if len(tied) > 1:
            confidence = AMBIGUOUS_CONFIDENCE
        else:
            confidence = round(0.95 * top_score, 3)
            if runner_up >= top_score - 0.15:
                confidence = min(confidence, 0.6)
        return NameMatch(tied, confidence, i + top_n, top_score, top_n, runner_up, tied)

    def find_name(self, toks: list[_Tok], start: int = 0, intro_ok: bool = True) -> NameMatch | None:
        """Name at the head of `toks[start:]`, skipping fillers and 'pour', 'appréciation de'."""
        i = start
        while i < len(toks) and i - start < 4:
            m = self.match_at(toks, i)
            if m:
                return m
            if toks[i].norm in _FILLERS or (intro_ok and toks[i].norm in _NAME_INTRO):
                i += 1
                continue
            break
        return None

    # ---- utterance -> items --------------------------------------------

    def structure(self, utterance: Utterance | str) -> list[CandidateItem]:
        text = utterance.text if isinstance(utterance, Utterance) else utterance
        stt_conf = utterance.confidence if isinstance(utterance, Utterance) else None
        items: list[CandidateItem] = []
        current: list[tuple[int, int]] = []  # sentence spans of the comment being built

        def flush() -> None:
            if current:
                item = self._comment(text, current[0][0], current[-1][1])
                if item:
                    items.append(item)
                current.clear()

        for s, e in _sentences(text):
            toks = _tokens(text[s:e], s)
            if not toks:
                continue
            command = self._command(text, toks, e)
            if command and command.kind == "correction_text" and current:
                current.append((s, e))  # "Léa, travail sérieux. Non, plutôt : travail régulier."
                continue
            if command:
                flush()
                items.append(command)
                continue
            if current and self.find_name(toks):
                flush()
            current.append((s, e))
        flush()
        if stt_conf is not None:
            for it in items:
                it.confidence = round(min(it.confidence, stt_conf), 3)
        return items

    def _command(self, text: str, toks: list[_Tok], end: int) -> CandidateItem | None:
        words = [t.norm for t in toks]
        head = 0
        while head < len(words) - 1 and words[head] in _FILLERS:
            head += 1
        first = words[head]
        if first in _STOP_WORDS and len(words) - head <= 4:
            return CandidateItem([], "", 0.95, "stop")
        if first in _UNDO_WORDS and len(words) - head <= 6:
            return CandidateItem([], "", 0.95, "undo")
        marker = _marker_at(words, head)
        if marker is not None:
            rest = toks[marker:]
            m = self.find_name(rest) if rest else None
            if m and m.end == len(rest):  # "non, plutôt pour Léa": the name is all there is
                return CandidateItem(m.student_ids, "", m.confidence, "reassign")
            body = _span_text(text, rest[0].start, end) if rest else ""
            return CandidateItem([], body, 0.9, "correction_text") if body else None
        if first in _REASSIGN_LEAD and "pour" in words[head + 1 : head + 8]:
            p = words.index("pour", head + 1)
            m = self.find_name(toks, p + 1, intro_ok=False)
            if m:
                return CandidateItem(m.student_ids, "", m.confidence, "reassign")
        return None

    def _comment(self, text: str, s: int, e: int) -> CandidateItem | None:
        toks = _tokens(text[s:e], s)
        name = self.find_name(toks)
        body_start = name.end if name else 0
        students = name.student_ids if name else []
        confidence = name.confidence if name else NO_STUDENT_CONFIDENCE
        # mid-sentence correction: what follows the last "non, plutôt" replaces what preceded it
        words = [t.norm for t in toks]
        cut = None
        for i in range(body_start, len(words)):
            if _marker_at(words, i) is not None and i > 0:
                cut = i
        if cut is not None:
            after = _marker_at(words, cut)
            rest = toks[after:]
            m = self.find_name(rest) if rest else None
            if m:
                students, confidence = m.student_ids, m.confidence
                rest = rest[m.end :]
            if rest:
                body = _span_text(text, rest[0].start, e)
            else:
                body = _span_text(text, toks[body_start].start, toks[cut].start) if body_start < cut else ""
        else:
            body = _span_text(text, toks[body_start].start, e) if body_start < len(toks) else ""
        if not body or not _TOKEN.search(body) or all(t.norm in _FILLERS for t in _tokens(body)):
            return None
        return CandidateItem(students, body, confidence, "comment")


def _sentences(text: str) -> list[tuple[int, int]]:
    spans, start = [], 0
    for m in _SENTENCE_END.finditer(text):
        spans.append((start, m.end()))
        start = m.end()
    if start < len(text):
        spans.append((start, len(text)))
    return spans


def _marker_at(words: list[str], i: int) -> int | None:
    """If a correction marker ("non, plutôt") starts at word `i`, the index right after it."""
    for a, b in _CORRECTION_MARKERS:
        if i + 1 < len(words) and words[i] == a and words[i + 1] == b:
            return i + 2
    return None


def _span_text(text: str, s: int, e: int) -> str:
    """The teacher's words between s and e, trimmed of leading punctuation, first letter capitalized."""
    body = text[s:e].strip().lstrip(",:;-–— ").strip()
    body = body.rstrip(",;:-–— ").strip()
    return body[:1].upper() + body[1:] if body else ""


# ---- pluggable LLM structurer (no network from here) ---------------------

LLM_PROMPT = """You split a French teacher's dictated utterance into report-card items.
Roster (student_id: names): {roster}
Return JSON: a list of objects {{"student_candidates": [student_id...], "text": str, "confidence": float, "kind": str}}
kind is one of {kinds}. "text" must be copied verbatim from the utterance, never invented.
When two students match equally, list both and set confidence below 0.5.
Utterance: {utterance}"""


class LLMStructurer:
    """Same interface as RuleBasedStructurer; `complete(prompt) -> str` is injected by the caller.

    Without a completion function it is a stub and raises NotImplementedError. Its output is
    validated: unknown kinds and student ids are dropped, and a text that is not a span of the
    utterance is rejected, so the model can never invent words.
    """

    def __init__(self, students: list[Student], complete: Callable[[str], str] | None = None):
        self.students = students
        self.complete = complete
        self._ids = {s.student_id for s in students}

    def prompt(self, text: str) -> str:
        roster = "; ".join(f"{s.student_id}: {', '.join(s.name_forms())}" for s in self.students)
        return LLM_PROMPT.format(roster=roster, kinds=", ".join(KINDS), utterance=text)

    def structure(self, utterance: Utterance | str) -> list[CandidateItem]:
        if self.complete is None:
            raise NotImplementedError("LLMStructurer needs a completion function; use RuleBasedStructurer")
        text = utterance.text if isinstance(utterance, Utterance) else utterance
        raw = json.loads(self.complete(self.prompt(text)))
        items = []
        for obj in raw if isinstance(raw, list) else []:
            kind = obj.get("kind")
            body = str(obj.get("text") or "").strip()
            if kind not in KINDS or (body and normalize(body) not in normalize(text)):
                continue
            ids = [i for i in obj.get("student_candidates") or [] if i in self._ids]
            conf = float(obj.get("confidence") or 0.0)
            if len(ids) > 1:
                conf = min(conf, AMBIGUOUS_CONFIDENCE)
            items.append(CandidateItem(ids, body, max(0.0, min(conf, 1.0)), kind))
        return items


# ---- applying items to the drafts awaiting approval ----------------------

@dataclass
class Draft:
    student_candidates: list[str]
    text: str
    confidence: float


@dataclass
class Drafts:
    """Items dictated but not yet written. Shows how kinds compose: reassign moves, never duplicates."""

    items: list[Draft] = field(default_factory=list)
    stopped: bool = False

    def apply(self, item: CandidateItem) -> str:
        """Apply one item; returns what happened, `undo_write` when the undo must go to the journal."""
        if item.kind == "stop":
            self.stopped = True
            return "stopped"
        if item.kind == "comment":
            self.items.append(Draft(list(item.student_candidates), item.text, item.confidence))
            return "added"
        if item.kind == "undo":
            if self.items:
                self.items.pop()
                return "removed_draft"
            return "undo_write"
        if not self.items:
            return "ignored"
        last = self.items[-1]
        if item.kind == "correction_text":
            last.text = item.text
            return "text_replaced"
        if item.kind == "reassign":
            last.student_candidates = list(item.student_candidates)
            last.confidence = item.confidence
            return "reassigned"
        return "ignored"
