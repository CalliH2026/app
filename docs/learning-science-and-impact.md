# Learning design and the business case

Research checked on 8 November 2026. Discovery used two Linkup deep searches, followed by inspection of original publisher/government pages. No private school records were sent. Mammouth was not needed. External evidence, Calli timings and scenario projections are separate.

## Compatible prompt changes

The activity retains three Pythagorean steps, the same JSON brief, output schema, offline HTML, sandbox and teacher review. Existing generated files, hashes and filmed exercise remain unchanged. New instructions affect future generation only.

| Design decision | Concrete instruction |
|---|---|
| Attempt before correction | Request an answer and structured reason; offer an optional hint. |
| Example then independent work | Within an existing step, offer a short worked example; vary numbers and fade help for the next attempt. |
| Explanatory feedback | Explain the specific misconception and allow retry; explain correct answers too. |
| Coherent representation | Keep triangle, labels and explanation together; avoid decorative movement during reasoning. |
| Revisit later | Suggest later practice; add no reminder system. Resetting in one session is not spaced learning. |

These choices draw on [Pashler et al., IES practice guide (2007)](https://ies.ed.gov/ncee/wwc/PracticeGuide/1), particularly recommendations 2 (worked examples), 3 (graphics and descriptions), 5b (quizzing) and 7 (explanation). The [EEF cognitive-science review](https://educationendowmentfoundation.org.uk/education-evidence/evidence-reviews/cognitive-science-approaches-in-the-classroom) provides classroom context; principles are not universal recipes or proof of Calli's effectiveness.

Mathematics-specific evidence warrants care. Murray, Horner and Göbel (2025) report a spacing effect of **g = 0.28**, 27 studies/53 effects. Testing versus restudy yielded **g = 0.18**, seven studies, with a 95% confidence interval including zero. These are standardized effects, not percentages; they do not establish a consistent retrieval advantage or an outcome for this AI exercise. [Original publisher abstract](https://link.springer.com/article/10.1007/s10648-025-10035-1). Linkup's initial summary gave g = 0.26/25 studies; the publisher's abstract is the retained value. No effect size appears in the video.

Linkup's application query now requests official curriculum explanations, worked examples and exercises with explanatory correction. The domain filter and returned-source validation remain intact. Curriculum material is not causal evidence. Only generic, identity-checked topics leave the app; the raw pupil report remains excluded from Devin's brief.

A live check of the revised generic Pythagorean query returned four results on three distinct allowed-domain URLs in 1.97 s. [Query receipt](research/linkup-v9-query-check.json). This checks retrieval, not pedagogical efficacy.

## Workload evidence

The DEPP report published November 2025, using the FPE 2022 survey, reports **41.1 hours/week outside holidays** for full-time secondary teachers. Across primary and secondary teachers together, the average is 41.4 hours; 33% is preparation/marking and 15% other activities. These shares are not secondary-only and are rounded. This is declared workload, not a measure of automatable tasks. [DEPP original report](https://www.education.gouv.fr/depp/le-temps-de-travail-des-enseignants-467782).

The EEF/NFER 2024 school-randomised trial involved **259 Year 7/8 science teachers in 68 English schools**. Measured lesson-preparation time averaged **56.2 versus 81.5 minutes/week**: **25.3 minutes, or 31%**, less. Teachers had a five-week familiarisation period; time was recorded in weeks 6–10. This concerns ChatGPT plus a guide for those lessons, not total working hours or Calli. Resource quality was reviewed; this result does not establish pupil attainment. [EEF original evaluation and report](https://educationendowmentfoundation.org.uk/projects-and-evaluation/projects/choices-in-edtech-using-generative-ai-chatgpt-for-ks3-science-lesson-preparation-2024-teacher-choices-trial).

## Calli's business scenario

The [annual model](annual-time-scenarios.md) is unchanged: median **43.1%** active-entry reduction under authored input distributions. The film rounds to **43%** and animates a normalized duration **100 → 57**; literal halving would overstate it.

The model's median annual school projection is 242.22 hours across 40 teachers, rounded to 240 hours. **240 / 8 = 30 standard eight-hour day equivalents.** This is pooled capacity, not 30 calendar days per teacher, staffing reduction or cash saving. The annual workload includes comments, meetings and outings; applying 43% to all school working time is invalid. Teacher/class/school totals overlap. Parent time is per household.

The business argument is capacity recovered from frequent small tasks while keeping existing software. Monetary value would be recovered hours × an explicitly chosen value/hour, less subscription, provider, setup and support costs. No euro ROI is asserted without a cost basis and measured adoption. No national headcount multiplier is used.

## Validation still needed

Time identical already-written comments manually and with Calli, counterbalance order, and separate active time from agent latency. Include corrections, failures, setup and review. To assess learning, compare a teacher-reviewed activity with matched practice, including a delayed test and new problems. Immediate success is not proof of durable learning. The film claims a learning-informed design, not measured attainment gains.
