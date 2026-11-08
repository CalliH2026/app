"""Voice A/B: name-assignment accuracy from two transcript files against truth.csv.

    python scripts/voice_ab.py --truth data/truth.csv \
        --with-vocab runs/voice-ab/with_vocab.csv --without-vocab runs/voice-ab/without_vocab.csv

See docs/voice.md for the protocol and voice/ab.py for the scoring rules.
"""

import sys
from pathlib import Path


def _main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from voice.ab import main

    return main()


if __name__ == "__main__":
    raise SystemExit(_main())
