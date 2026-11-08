# Annual active-time scenarios

These are workload projections, not measured human savings. The only observed input used in the entry model is the length of the prepared comments: 1,291 characters and 215 dictated words across ten comments. All typing rates, durations, frequencies and intervention rates are explicit assumptions. The recorded 25.57-second native write and 16.29-second family agent run measure machine execution, not human time saved.

## Scenario outputs

The video uses rounded medians from 100,000 input draws, seed 20261108. P10 and P90 are percentiles of the chosen model inputs, not statistical confidence limits for a real population.

| Unit | P10 | P50 | P90 |
|---|---:|---:|---:|
| Active comment-entry reduction | 32.8 % | 43.1 % | 52.3 % |
| Teacher / year | 4.6 h | 6.1 h | 7.5 h |
| Class / year | 9.3 h | 12.1 h | 15.1 h |
| School / year | 185.4 h | 242.2 h | 301.4 h |
| Parent household / year | 1.9 h | 3.1 h | 4.3 h |

Teacher, class and school numbers describe overlapping aggregates; do not add them. The parent unit is one household of two children, not each parent separately. This is the impact of selected tasks, not a percentage of the whole workday or school budget.

## Annual workload

- Teacher: 150 pupils, three terms, 450 already-written comments to enter; 20 parent-meeting preparations; two school-trip preparations; 30 minutes setup deducted.
- Class: 30 pupils, ten subjects, three terms. Aggregate 900 comments and the allocated share of meeting/trip preparation.
- School: 20 classes, 30 pupils per class, 40 teachers. The class and teacher models both imply 18,000 comment entries. Four school-trip preparations per class are implied by the allocation.
- Family: two children, 36 weekly reviews, four school-trip payments; five minutes setup deducted.

Assume use for every eligible occurrence. If adoption is lower, scale activity counts and retain applicable setup costs. Maintenance, integration costs, service costs and learning effects are not modelled.

## Inputs and arithmetic

For each comment: `manual seconds = 60 × 129.1 / typing_cpm + navigation + 8 seconds review`; `assisted seconds = 60 × 21.5 / dictation_wpm + turn handling + 8 seconds review + intervention_probability × intervention_seconds`. The same review allowance is used in both paths. Drafting the assessment and deciding a grade are excluded.

The older deterministic central scenario, without error correction, remains reproducible: 225 characters/minute, 100 words/minute, 4 seconds navigation versus 3 seconds turn handling. It gives 464.267 seconds versus 239 seconds for ten comments, 48.521% less active entry time.

Sensitivity uses independent triangular distributions with `(minimum, mode, maximum)`. Each draw describes an actor/year, not thousands of independently sampled pupils; school and class outputs scale the same scenario rather than artificially narrowing uncertainty.

| Parameter | Minimum | Mode | Maximum |
|---|---:|---:|---:|
| typing_cpm | 150 | 225 | 300 |
| dictation_wpm | 85 | 100 | 130 |
| manual_navigation_seconds | 2 | 4 | 7 |
| dictation_turn_seconds | 2 | 3 | 5 |
| meeting_manual_minutes | 10 | 15 | 20 |
| meeting_assisted_minutes | 4 | 6 | 10 |
| outing_manual_minutes | 40 | 60 | 90 |
| outing_assisted_minutes | 15 | 25 | 40 |
| weekly_family_manual_minutes | 5 | 8 | 12 |
| weekly_family_assisted_minutes | 2 | 3 | 5 |
| assisted_intervention_probability | 0.01 | 0.05 | 0.15 |
| assisted_intervention_seconds | 15 | 30 | 90 |

The parent payment scenario assumes 4 minutes manually versus 1.5 minutes assisted. It is an illustrative workflow assumption; the Stripe adapter has not yet been verified against an account.

## Errors and interruptions

The Monte Carlo model penalises the assisted path with a hypothetical intervention rate of 1–15% and 15–90 seconds per intervention. It gives no credit for fewer human typos in the headline. A separate optional example assumes 3% manual corrections at 15 seconds each and 5% assisted interventions at 30 seconds each. These are not measured error rates. They are sensitivity inputs to replace with an observed study.

A real validation would time matched tasks, record corrections in both paths, separate active work from unattended agent time, and repeat across teachers and family sizes. Do not report this simulation as such a study.

## Reproduce

Run `python video/calli-v8/annual_estimates.py`. [Machine-readable assumptions and outputs](../video/calli-v8/annual-estimates.json) accompany [the source](../video/calli-v8/annual_estimates.py). No network or provider key is used.
