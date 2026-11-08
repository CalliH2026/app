# Vendored: Francois Amat's H Parallel (school outing, Pythagore practice)

- Upstream: `Fran-cois/H-Hack-nov26`, main `392f137` (for these files identical to `7e62463`, archive SHA256
  `43be3d462a610a79ebc9f0fa3f79a537aba3124d527cbce39ae7e7b69201a691`). Shared by its author for this hackathon;
  bug fixes authorized by the user. No license is claimed beyond that.
- Only the import closure of `outings.py` and `practice.py` is copied, with the tests that do not need upstream's
  `app.py`. Upstream auth, pronotepy connector, pilot, native observers, Discord exports and credentials are not
  copied.
- `MANIFEST.json` lists each file's SHA256 and the upstream's: `unchanged` files are byte-identical; `patched`
  files (practice, outings, native_bridge and their tests) equal upstream plus `patches/000*.patch` (a `git format-patch` series that applies with `git am` on
  upstream main, offered for review upstream; Francois's main is not changed); `conftest.py` is a Calli addition
  that keeps test state out of the tree.
- Patches, in the order of upstream review PR Fran-cois/H-Hack-nov26#2: 0001 bare 32-hex v3 session IDs; 0002 visit
  facts cited by exact key and matching value; 0003 a finished session waiting for the user; 0004 a generator's own
  CSP meta; 0005 the documented v3 attachment endpoint; 0006 (upstream test only, not vendored) the
  `teacher_assessment` argument in `test_background_pronote.py`; 0007 Francois's own `87c1724` ("Preserve Devin
  sessions when optional URLs are malformed"), applied verbatim with his authorship from a root-supplied patch
  (SHA256 `91ddd2434d37c0227951da297b65585cdf53fc8500f2fc76d11ab8aaacd7ed8b`); 0008 the native companion token is
  created on first use, not as a side effect of importing `native_bridge`; 0009 a Holo4 timeout is named
  (`h_outcome`, `h_error`) and the cancel request is recorded as unconfirmed (`session_cancel`).
- Run its tests: `pip install -e '.[parallel]' pytest` then `pytest vendor/h_parallel`. Voices for the report
  scenarios: `python -m vendor.h_parallel.video` (say on macOS, espeak-ng on Linux); they are synthetic, not STT proof.
