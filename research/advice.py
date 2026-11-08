"""One short, sourced suggestion to refine the advice part of an approved comment (Linkup).

When the teacher approves a comment on the approval screen, Calligraphe may propose one
sentence, in French and addressed to the student, drawn from education research (retrieval
practice, spaced practice, feedback, self-regulation, attention, note-taking), with its source.
The teacher appends it with "Ajouter" or ignores it; nothing is ever added without that click.

`suggest` never raises: no LINKUP_API_KEY, a failed call or a sentence that does not meet the
constraints all give None. Only the comment text is sent, with the roster's names replaced by
"l'élève". Results are cached by normalized comment text in
runs/advice-cache.jsonl, so the same comment never waits twice.

Environment: LINKUP_API_KEY (never printed). Needs the optional extra: pip install -e ".[research]".
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from agent.queue import normalize

DEFAULT_CACHE = Path("runs/advice-cache.jsonl")
MAX_CHARS = 160
TIMEOUT_S = 30.0

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "description": "one sentence in French, addressed to the student (tu), "
                                                  f"concrete, at most {MAX_CHARS} characters"},
        "source_name": {"type": "string", "description": "title of the research source or its publisher"},
        "source_url": {"type": "string", "description": "URL of the research source"},
    },
    "required": ["text", "source_name", "source_url"],
}

_SENTENCE_BREAK = re.compile(r"[.!?…]\s+\S")
_WORD = re.compile(r"[a-zà-ÿœæ]+", re.IGNORECASE)
_FRENCH_WORDS = frozenset({
    "tu", "te", "t", "ton", "ta", "tes", "toi", "vous", "votre", "vos", "de", "du", "des", "la", "le", "les", "l",
    "un", "une", "pour", "et", "à", "au", "aux", "en", "avec", "sans", "chaque", "avant", "après", "puis", "ce",
    "cette", "ces", "qui", "que", "ne", "pas", "plus", "sur", "dans", "par",
})


@dataclass(frozen=True)
class Suggestion:
    text: str
    source_name: str
    source_url: str


def redact(text: str, names: Iterable[str]) -> str:
    """`text` with every whole-word occurrence of a name (case-sensitive, longest first) replaced by "l'élève"."""
    for name in sorted({n.strip() for n in names if n and n.strip()}, key=len, reverse=True):
        text = re.sub(rf"(?<![\w-]){re.escape(name)}(?![\w-])", "l'élève", text)
    return text


def build_query(comment_text: str) -> str:
    return (
        "A teacher wrote this report-card comment for a secondary-school student, in French: "
        f"\"{comment_text.strip()}\". Identify the learning difficulty it describes (for example attention "
        "errors, irregular work, little oral participation, approximate note-taking, written work below the "
        "homework) and give one evidence-based study strategy from the cognitive science of learning "
        "(retrieval practice, spaced practice, feedback, self-regulation, attention, note-taking) that matches it. "
        f"Answer with one concrete sentence in French, addressed to the student (tu), at most {MAX_CHARS} "
        "characters, and the name and URL of the research source that supports it."
    )


def _field(obj: Any, name: str) -> str:
    value = obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)
    return str(value or "").strip()


def validate(text: str, source_name: str, source_url: str) -> Suggestion | None:
    """The suggestion if it is one French sentence of at most MAX_CHARS characters with an http(s) source."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text or len(text) > MAX_CHARS or text[-1] not in ".!?…" or _SENTENCE_BREAK.search(text[:-1]):
        return None
    if not _FRENCH_WORDS.intersection(w.lower() for w in _WORD.findall(text)):
        return None
    url = (source_url or "").strip()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    name = re.sub(r"\s+", " ", source_name or "").strip() or parts.hostname
    return Suggestion(text=text, source_name=name, source_url=url)


def _from_structured(response: Any) -> Suggestion | None:
    data = response.get("data", response) if isinstance(response, dict) else getattr(response, "data", response)
    return validate(_field(data, "text"), _field(data, "source_name"), _field(data, "source_url"))


def _from_sourced_answer(response: Any) -> Suggestion | None:
    answer = _field(response, "answer")
    for src in getattr(response, "sources", None) or []:
        s = validate(answer, _field(src, "name"), _field(src, "url"))
        if s is not None:
            return s
    return None


def ask(comment_text: str, client: Any) -> Suggestion | None:
    """One Linkup call (structured, else sourcedAnswer); may raise if both are unavailable."""
    query = build_query(comment_text)
    try:
        response = client.search(query=query, depth="standard", output_type="structured",
                                 structured_output_schema=json.dumps(SCHEMA), timeout=TIMEOUT_S)
    except Exception:
        response = None
    if response is not None:
        return _from_structured(response)
    return _from_sourced_answer(client.search(query=query, depth="standard", output_type="sourcedAnswer",
                                              timeout=TIMEOUT_S))


def cache_key(comment_text: str) -> str:
    return normalize(comment_text).casefold()


class _Miss:
    pass


MISS = _Miss()


def read_cache(path: Path, key: str) -> Suggestion | None | _Miss:
    """The cached result for `key` (the last line wins), None if cached as no suggestion, MISS if absent."""
    found: Suggestion | None | _Miss = MISS
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return MISS
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict) or rec.get("key") != key:
            continue
        s = rec.get("suggestion")
        found = validate(_field(s, "text"), _field(s, "source_name"), _field(s, "source_url")) \
            if isinstance(s, dict) else None
    return found


def write_cache(path: Path, key: str, suggestion: Suggestion | None) -> None:
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        rec = {"key": key, "suggestion": asdict(suggestion) if suggestion else None, "ts": round(time.time(), 3)}
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def default_client() -> Any:
    from linkup import LinkupClient  # optional extra `research`, imported only when a key is set

    return LinkupClient(api_key=os.environ["LINKUP_API_KEY"])


def suggest(comment_text: str, *, client: Any = None, cache_path: Path = DEFAULT_CACHE,
            names: Iterable[str] = ()) -> Suggestion | None:
    """One sourced suggestion for this comment, or None. Never raises.

    `names` (the roster's name forms) are replaced by "l'élève" before anything is sent or cached.
    """
    try:
        comment_text = redact(comment_text, names)
        key = cache_key(comment_text)
        if not key:
            return None
        if client is None and not os.environ.get("LINKUP_API_KEY"):
            return None
        cached = read_cache(cache_path, key)
        if not isinstance(cached, _Miss):
            return cached
        if client is None:
            client = default_client()
        result = ask(comment_text, client)
        write_cache(cache_path, key, result)
        return result
    except Exception:
        return None
