# Voice input

Two modules (SPEC.md section 3.1, components 1 and 2):

- `voice/gladia_live.py`: Gladia live speech-to-text through the official SDK (`gladiaio-sdk`), model `solaria-1`, French only, the class roster sent as custom vocabulary. Exposes `final_utterances(audio_chunks, init_request)`, an async generator of `Utterance(text, start, end, confidence)`.
- `voice/structurer.py`: turns one utterance into zero or more candidate items `{student_candidates, text, confidence, kind}` with kind `comment`, `correction_text`, `reassign`, `undo` or `stop`. Rule-based; `LLMStructurer` is a pluggable alternative with an injected completion function and no network call of its own.

## Setup

```sh
pip install -e ".[dev,voice]"      # add ",mic" for microphone mode (sounddevice, needs PortAudio)
export GLADIA_API_KEY=...          # read at runtime only, never printed or logged
```

The roster is `data/roster.csv` (`student_id, display_name, aliases`, aliases separated by `|`), override with `--roster`. Every first name, last name and alias becomes one custom-vocabulary entry (deduplicated), `default_intensity` 0.5 as Gladia recommends (0.4 to 0.6).

## Run

File mode streams a 16-bit PCM WAV at real-time pace (one Gladia session per file, `item_id` = file stem). Supported sample rates: 8000, 16000, 32000, 44100, 48000 Hz.

```sh
python -m voice.gladia_live --file sample.wav --structure
python -m voice.gladia_live --file sample.wav --no-vocab          # without the roster vocabulary
python -m voice.gladia_live --file audio/*.wav --out transcript.csv
```

Microphone mode streams the default input device at 16 kHz mono until Ctrl-C:

```sh
python -m voice.gladia_live --mic --structure --out runs/mic.csv
```

Each final utterance is printed as one JSON line; `--structure` adds the candidate items under it; `--out` writes a CSV `item_id, text, start, end, confidence`. Other options: `--endpointing` (seconds of silence that close an utterance, default 0.5), `--fast` (file mode: send audio as fast as possible).

Session parameters, from Gladia's recommended parameters for live STT: `language_config = {languages: ["fr"], code_switching: false}` (one known language), `endpointing` 0.5 and `maximum_duration_without_endpointing` 15 (the meeting-recorder profile: a teacher pauses while thinking, the voice-agent value of 0.05 to 0.1 would cut comments in two), partial transcripts off (only finals are used).

## What the structurer understands

| Said | Kind | Result |
|---|---|---|
| "Léa Martin, participe bien." | comment | `[s01]`, "Participe bien." |
| "Léa, très bon trimestre." with two Léa | comment | both ids, confidence 0.4: the UI asks |
| "Pour Maëlle, ..." with Maël and Maëlle | comment | both ids (homophones), confidence 0.4 |
| "Max, ..." (alias) | comment | the student whose alias is Max |
| "Hugo, travail sérieux, non plutôt, travail irrégulier." | comment | text after the last "non, plutôt" only |
| "Non, plutôt : participe activement." | correction_text | replaces the previous item's text |
| "Non, cette remarque était pour Zoé." | reassign | moves the previous item (no duplicate) |
| "Annule la dernière." | undo | removes the last draft, or undoes the last write via the journal |
| "Stop." | stop | |

Names are matched at the head of each sentence (after fillers such as "euh", "alors", "pour"), accent- and case-insensitively, with a fuzzy score and a rough French phonetic key. Short names (3 letters or fewer) match exactly or phonetically only. The text is always a span of the utterance, never generated. Known limitation: a sentence that starts with another student's name opens a new item ("... Hugo l'aide beaucoup." becomes an item for Hugo); the teacher sees it in the approval UI.

## A/B protocol: custom vocabulary on and off (SPEC.md section 6 item 9)

Goal: name-assignment accuracy on the same 10 utterances, with and without the roster as custom vocabulary. This is the Gladia evidence; no number is reported until it has been run.

1. Write the truth file before recording: `item_id, student_id, text`, 10 rows (the `truth.csv` format of SPEC.md section 5). Include the demo cases: two identical first names said with the full name, one homophone, one nickname.
2. Record one WAV per row, named `<item_id>.wav`, 16 kHz mono 16-bit, the teacher reading "<name>, <text>" naturally, e.g. in `audio/ab/` (audio of team members only, not committed).
3. Transcribe the same files twice, in the same conditions:

   ```sh
   mkdir -p runs/voice-ab-$(date +%Y%m%d-%H%M)
   python -m voice.gladia_live --file audio/ab/*.wav --out runs/voice-ab-.../with_vocab.csv
   python -m voice.gladia_live --file audio/ab/*.wav --no-vocab --out runs/voice-ab-.../without_vocab.csv
   ```

4. Score both arms:

   ```sh
   python scripts/voice_ab.py --truth data/truth.csv \
       --with-vocab runs/voice-ab-.../with_vocab.csv --without-vocab runs/voice-ab-.../without_vocab.csv \
       --json runs/voice-ab-.../ab.json
   ```

The script runs the rule-based structurer on each item's transcript and reports, per arm: `correct` (exactly the true student), `abstained` (several candidates including the true one: the UI would ask), `wrong`, `missing` (no transcript), `name accuracy` = correct / n, and `name in transcript` (the true student's name or alias appears in the transcript, the raw effect of the vocabulary). Commit the two transcripts and `ab.json` in `runs/`: they are the evidence behind the number.

### Result, 7 November 2026, synthetic dictation (first measurement)

No teacher's voice was available on Saturday afternoon, so the ten demo and measured utterances of `data/truth.csv` (items t01 to t13, five demo and five measured) were read by the Mac's French voice (`say -v "Flo (Français (France))" -r 170`, "<display name>, <text>"), converted to 16 kHz mono WAV, and transcribed twice at real-time pace. Evidence in `runs/voice-ab-20261107-1330/`.

| arm | n | correct | abstained | wrong | name accuracy |
|---|---|---|---|---|---|
| with vocabulary | 10 | 8 | 0 | 2 | 8/10 |
| without vocabulary | 10 | 8 | 0 | 2 | 8/10 |

Reading: the transcripts are good (confidences 0.59 to 0.76; comment texts nearly verbatim, with small slips such as "trimestre en demi-temps" for "demi-teinte" and "un câble" for "un cap"); the two misses are names rendered as common words ("Mélagie rare", "Il est depuis") in both arms. On synthetic speech the custom vocabulary made no measurable difference; the test that matters is the one with a real voice, which this protocol runs unchanged. The structurer bug that crashed `--structure` on an `Utterance` object was fixed the same afternoon.

## Tests

`pytest` runs without network or key: the Gladia session is replaced by a fake with the SDK's async-session surface, and the structurer is tested on fake utterance streams covering the demo cases (`tests/test_gladia_live.py`, `tests/test_voice_structurer.py`, `tests/test_voice_ab.py`). The test roster is `tests/fixtures/roster.csv` (fictitious).
