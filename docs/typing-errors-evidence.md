# Typing errors: evidence and sensitivity audit

The submitted **43.1% median active-entry estimate remains unchanged**. This review asks whether manual corrections justify increasing it. It preserves the 100,000 draws and seed of the [existing model](annual-time-scenarios.md), including assisted interventions.

## Primary research

Dhakal, Feit, Kristensson and Oulasvirta, CHI 2018, studied 168,960 volunteers. Mean typing speed was 51.56 five-character words/minute, correction keys represented 6.31% of keystrokes, and keystrokes per final character averaged 1.173. Crucially, elapsed typing time already includes corrections between the first and last keypress. Multiplying this measured net typing time by 1.173 would count corrections twice. These were not French teachers using PRONOTE.

[Primary paper, definitions and Table 3](https://userinterfaces.aalto.fi/136Mkeystrokes/resources/chi-18-analysis.pdf).

## Additional repair scenarios

The values below add hypothetical **extra** manual repair time beyond what is already included in typing speed and review. The assisted path and all other inputs stay unchanged. They are neither measured error rates nor a claim that corrections take this long.

| Extra manual repair per comment | Median active-entry reduction |
|---|---:|
| 0 seconds | 43.1% |
| 0.45 seconds | 43.6% |
| 1.5 seconds | 44.9% |
| 3 seconds | 46.5% |
| 6 seconds | 49.6% |

For example, 0.45 seconds is the expected cost of an assumed 3% repair probability at 15 seconds per repair. Around 6.44 additional manual seconds per comment would be needed for this model’s median to reach 50%; the research above does not establish that additional cost. This is an inverse sensitivity calculation, not a measured finding.

[Machine-readable results](research/entry-error-sensitivity.json). The original deterministic scenario, without assisted intervention costs or uncertain inputs, gives 48.5%. It must not be confused with the current distributional result.

The evidence supports keeping the submitted estimate and reporting measured agent timings separately. A real comparison should time matched entry tasks, count remaining errors and corrections on both sides, and distinguish active human work from unattended latency.
