# National impact scenario — France

The film displays **57,700 establishments**, **about 3 million hours per year** and **about €120 million of annual gross time value**. The latter two numbers are a full-adoption scenario for **secondary teachers only**, not observed savings, an adoption forecast or an estimate of cash released from public budgets.

## Official population and model

DEPP's [Education nationale en chiffres, 2026 edition](https://www.education.gouv.fr/depp/l-education-nationale-en-chiffres-edition-2026-505326), published 25 August 2026, reports 2025–2026 figures: 47,000 primary schools, 7,000 collèges, 3,700 lycées and 485,450 secondary teachers. Establishment totals provide context; **teacher headcount is the multiplier**. Primary teachers, higher education and other ministries are not included in the projection.

The existing [annual workload model](annual-time-scenarios.md) gives a median 6.0555 hours freed per teacher per year across selected tasks: entry of 450 already-written comments, 20 meeting preparations and two outings, including setup and modelled assisted interventions. These are illustrative task assumptions; no human comparison established them. The 43% entry reduction is not a reduction of the teacher's entire working year.

```
485,450 secondary teachers × 6.055537943 h/year = 2,939,660.895 h/year
2,939,660.895 h × assumed €40/h = €117,586,435.78/year
Video rounding: ~3M hours and ~€120M/year
```

€40/hour is an explicit valuation assumption, not an official teacher salary or marginal employer cost. It is deliberately separate from DEPP headcounts. See [machine-readable calculation](../video/calli-v11/national-scenario.json).

| Scenario | Annual hours | Gross value at €40/h |
|---|---:|---:|
| 10% adoption | 293,966 | €11.76M |
| 25% adoption | 734,915 | €29.40M |
| 100% adoption | 2,939,661 | €117.59M |

At full adoption, changing the valuation to €25–60/h gives about €73–176M. The original time model's P10–P90 translates to 2.25–3.66M hours; these are input sensitivities, not statistical confidence intervals. A national forecast would also require population-specific workloads and an adoption model.

## Who benefits, and what is excluded

Teachers could use freed capacity for teaching and pupil support. Schools and public employers could benefit from service quality and capacity; that does not automatically reduce payroll. The family view addresses parents' navigation burden, and administrative/local-authority workflows could add value, but those populations and workloads have not been validated. **Do not add an arbitrary percentage of the education budget or count the same teacher time again under schools or collectivités.**

Technology, agent/API execution, hosting, maintenance, deployment, training and integration costs have not been deducted. No net ROI, reduction in staffing, error-prevention benefit or cash saving is established. A pilot should measure active human time on matched tasks, completion quality, interventions and costs, then estimate net annual value for each distinct actor.

## Provenance

The DEPP source was verified directly on 8 November 2026. A separate Linkup lookup returned no usable source; it is retained as such in research evidence. The learning-science research used by the product is separately documented in [learning-science-and-impact.md](learning-science-and-impact.md).
