"""`python -m asthra` — start ASTHRA and open it in the browser."""
from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["serve", "--open"]))
