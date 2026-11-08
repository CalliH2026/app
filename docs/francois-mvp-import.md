# Francois's workspace in this repository (mvp/)

`mvp/` is Francois Amat's teacher workspace from `Fran-cois/H-Hack-nov26`, imported as files (not a merged history):

1. main `1974f6a708371f284048a8a38fb889e3954cfbfd`, rebuilt from the `7e62463` source archive (SHA256
   `43be3d462a610a79ebc9f0fa3f79a537aba3124d527cbce39ae7e7b69201a691`) plus `git diff --binary 7e62463..1974f6a`;
   all 197 `mvp/` blobs match `git ls-tree -r 1974f6a mvp`;
2. his review PR #3 at `40ee191` (lazy bridge token, Holo4 timeout metadata), from the diff `1974f6a..40ee191`;
3. the Calli changes, also offered upstream as patches (see `mvp/CALLI.md`): fictional AI pupil photos, the optional
   Appreciations module `mvp/calli_module.py` styled with the shell's H tokens, Calli's ten native pupils read-only in
   "Mes élèves", the outing display fix, an optional ElevenLabs voice, and the naming: New Pronote (Francois's
   original wordmark) is the interface, Calli (formerly "Parallèle") is the assistant.

4. main `349bd28dae00cf951be458025a7e866345980dce` (local Stripe collection simulation for school outings and the
   official Stripe mark), applied unchanged with `git apply` from GitHub's patch of that commit (SHA256
   `41489e4cef6d621bc04a5bf27d41d8d372ac71090224cc1fe8dc2d464e5d4732`, 10 files under `mvp/`). It calls no Stripe API and
   collects no funds: previews point to `checkout.example.invalid`. Calli's review tests are in
   `mvp/test_calli_outing_payments.py`.

Only `mvp/` is imported; its product documentation is `mvp/README.md`. His personal root README, Discord exports,
personal documents, credentials, event resources and generated voices are not imported. His history stays in his repository; this repository records the
import above. `vendor/h_parallel/` is the earlier, narrower vendored copy behind Calli's standalone `/sortie` and
`/entrainement` views and is unchanged.

Run his tests: `pip install -e '.[shell,dev]'`, generate the synthetic voices with `python -m mvp.video`
(`say` on macOS, `espeak-ng` on Linux; not speech-to-text proof), install `pdftotext` (poppler), then `pytest mvp`.

Redactions in this repository only (not in the upstream patches): the personal contact address on `/privacy`
(`mvp/auth.py`) and a personal home path in `mvp/README.md`. Everything else in `mvp/` matches the upstream patch result.
