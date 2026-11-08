# Calli: mechanism, application and experience

**Calli works alongside you: it understands your context, prepares useful work, and operates the software you already use.**

Education is the first demonstrated application. The reusable idea is assistance connected to an ongoing task: observe relevant context, prepare a useful next step, and use the appropriate tool or existing interface to carry out the user's intent.

## Three dimensions, one product

| Dimension | User value | Evidence in the current product |
|---|---|---|
| Mechanism | Useful preparation while the user continues working; functions for structured operations, computer use for the existing interface. | Registered document opening in Calli triggers source-bound preparation. H chooses tools; independent school-trip collectors overlap. Holo operates the native PRONOTE client. |
| Application | Less repetitive entry and a clearer path from a pupil's work to useful support. | Dictation → guarded queue → PRONOTE write/read-back; sourced report → Devin-generated exercise; partial school-trip dossier. |
| Experience | Present the relevant result, source and next action to each user. | Coherent New Pronote/H interface, separate teacher and parent views, per-child family summaries, and a landing page that explains the product. |

These are complementary contributions to a single team product. Credit the team together: **François, Wilfred, Liqin**.

## Twenty-second pitch

> Calli is an assistant that works alongside you. Open a document, and it prepares useful help while you continue. Give it a task, and it combines function calls with computer use to work in your existing software. We demonstrate that in education: PRONOTE comments, targeted exercises, school-trip preparation and a clearer family overview.

The demo should lead with the trigger and the overlapping work: **you open a document → Calli starts preparing useful help → you continue your task**. This context-triggered preparation is the central idea. Running independent tools concurrently is a complementary implementation technique. A short **Observe → Prepare → Act** opening explains the mechanism; the product footage supplies the outcomes. Role labels explain the change of perspective when moving from the teacher to the parent.

## H terminology and partner roles

H's Agents API calls developer-supplied functions **[custom tools](https://hub.hcompany.ai/agents-api/custom-tools)**. They complement the environment's computer-use actions, such as clicking and typing. The Models API calls Holo's OpenAI-style tool interface **[function calling](https://hub.hcompany.ai/models-api/build-an-agent/function-calling)**. In Calli, the clearest description is **Holo combines computer use with custom tools implemented in Python**.

The product decides which context event starts a job. H selects tools; our executor runs independent outing collectors concurrently and returns their results. These are different responsibilities: the current outing implementation is not evidence that H autonomously created a team of subagents. Nor does the saved preparation scene prove continuous observation of every desktop action.

Credit partners at their point of use: **H / Holo** for computer use and custom tools, **Gladia** for transcription, **Linkup** for research, and **Cognition / Devin API** for the generated interactive exercise. The provider logos are existing official assets with provenance in [SOURCE.md](../mvp/static/sponsors/SOURCE.md). Google Calendar and Stripe are not presented as completed integrations in this recorded flow.

## Keep claims attached to evidence

- Observation currently covers registered document openings inside Calli. OS-wide observation and general prediction of user intent are future work.
- Source preparation and native writing are separate flows. Opening a document does not silently write a report comment; explicit completed dictation supplies that request.
- The outing pool demonstrates concurrent independent collectors. It does not prove all product jobs run in parallel or that the entire system has general multi-agent autonomy.
- The exercise is interactive in the teacher preview; a separate authenticated student account is not demonstrated.
- Administration and attendance appear in the product vision, not as shipped workflows in the film.
- Measured agent timings and the estimated human active-time reduction remain distinct. No new timing or customer testimonial is inferred from the positioning.

See the [use cases](calli-use-cases.md), [architecture](calli-system.md) and [API evidence](calli-api-and-architecture.md). The [revised English deck](pitch/speaker-notes.md) opens with the general promise and the mechanism before the educational proof. The [narrated video revision (v7)](release.md) carries the same positioning, with contextual partner logos, aligned captions, no measured oral silence longer than 0.8 seconds, and an unchanged product timeline. Earlier [opening-only alternatives](calli-use-cases.md) remain available; the submitted YouTube link still points to v5 until a replacement is selected and uploaded.
