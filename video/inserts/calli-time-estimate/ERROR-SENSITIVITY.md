# Calli time model: error and repair sensitivity

**Hypothetical scenarios, not observed error rates.** This appendix does not change the ≈ 50 % headline.
Data: `calli-erreurs-sensibilite.json` (from Root, numbers unchanged); recomputed by `tests/test_calli_time_model.py`.

Repair time is added to **both** arms: typing corrections on the manual side; transcription (ASR) corrections and
human repair after GUI incidents on the Calli side. Review time already in the base model is not counted again.

```
H = H0 + n * p_manual * c_manual
C = C0 + n * (p_asr * c_asr + p_gui * c_gui)
gain = 100 * (1 - E[C] / E[H])          H0 = 464.267 s, C0 = 239.0 s, n = 10
```

| Scenario | Extra manual | Extra Calli | Estimated active-time gain |
|---|---:|---:|---:|
| Base, no additional repair | 0 s | 0 s | 48.521 % |
| Equal extra repair (10 % × 15 s each side) | 15 s | 15 s | 47.002 % |
| More Calli repairs (ASR 20 % × 15 s, GUI 10 % × 30 s) | 15 s | 60 s | 37.613 % |
| Adverse for Calli (ASR 40 % × 30 s, GUI 20 % × 60 s) | 15 s | 240 s | 0.056 % |

The gain vanishes when Calli needs about **225.267 s more** human repair than the manual path for the 10 comments
(22.5 s per comment), in this central scenario only.

Limits: probabilities and durations are illustrative inputs; no confidence interval or population claim; the gain is
a ratio of expected times; undetected errors remain a quality risk at zero time cost; never count only human errors.
