# Sourced suggestion after approval (Linkup)

**What it does.** When the teacher clicks Approve on the approval screen, Calligraphe may show one short sentence under the comment, in French and addressed to the student, that refines its advice part with a study strategy from education research (retrieval practice, spaced practice, feedback, self-regulation, attention, note-taking), with the name of its source linked to the source's URL.

**Where the sentence comes from.** `research/advice.py` sends the comment text to Linkup, with every roster name replaced by "l'élève", with a query asking for one evidence-based strategy matching the difficulty the comment describes, and its source. The answer is kept only if it is a single sentence of at most 160 characters with an http(s) source; otherwise nothing is shown. Results are cached by normalized comment text in `runs/advice-cache.jsonl` (not committed). Without `LINKUP_API_KEY`, or when the call fails, there is no suggestion and the screen is unchanged.

**What the teacher controls.** The sentence is appended to the comment only when the teacher clicks "Ajouter"; a second Approve queues the text as it is shown, with or without the sentence, and the teacher can still edit it with Correct. The queued text is always exactly what is on screen.

**What it does not do.** It never writes anything by itself: it does not touch the queue, the comment or the school application. It is not a pedagogical authority: the sentence is a search result with a source to check, and the teacher's judgment decides.
