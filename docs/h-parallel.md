# H Parallel in Calli: school outing and Pythagore practice

Francois Amat's outing and practice code is vendored unchanged except for the patches listed in
`vendor/h_parallel/PROVENANCE.md`. Calli adds two secondary views next to `/workspace`, which is unchanged.

## Launch

```
pip install -e '.[parallel]'
python -m ui.app --workspace-dir work/ws --parallel-dir work/hp
```

- `/sortie`: Holo4 (`holo4-27b`) on an ephemeral H cloud workstation checks the visit on the official site
  (Linkup), the route (OSRM, driving estimate without traffic) and the fictional class, then pre-fills the dossier.
  Unknown facts stay "non confirmé" and an incomplete budget says what is missing. Nothing is sent to families
  and nothing is written to PRONOTE. Needs `HAI_API_KEY` (or `H_COMPANY_API_KEY`) and `LINKUP_API_KEY`.
- `/entrainement?job=<id>`: from a ready H analysis of the fictional Pythagore copy, `simulation` uses the bundled
  demo page (labelled, no Devin call); `live` opens one Devin v3 session (2 ACU max, no repo, no secrets). The
  activity is shown in a sandboxed frame and can be downloaded only after "J'ai relu l'activité". Needs
  `DEVIN_API` (or `DEVIN_API_KEY`); `DEVIN_ORG_ID` is resolved by `scripts/parallel_live.py` via `GET /v3/self`.
- An H analysis without video: `python scripts/parallel_live.py report --data-dir work/hp --condition cold`.

Without `--parallel-dir` the two pages say they are off and no `/api/parallel` route exists.

## What is and is not verified

- Provider test claims (Devin's browser and math tests) are reported, not re-run by Calli; Calli checks the file's
  structure and serves it with a sandbox CSP.
- Outing excerpts are the provider's quotations; the workstation screenshot proves navigation, not page content.
- Timings and success criteria for live runs: `docs/benchmark-protocol.md` and `scripts/parallel_live.py`.
