# Voice A/B, 7 November 2026, synthetic dictation

Ten utterances of `data/truth.csv` read by the macOS French voice "Flo (Français (France))" at rate 170
(`spoken.csv` has the exact spoken strings), converted to 16 kHz mono 16-bit WAV, transcribed by Gladia live
twice at real-time pace: `with_vocab.csv` (roster as custom vocabulary) and `without_vocab.csv`.
Scored with `scripts/voice_ab.py --truth truth10.csv`; result in `ab10.json`. Audio files are not committed
(regenerate with `say`). See docs/voice.md for the reading.
