"""urd — une des trois Nornes (voir yggdrasil.toile)."""

import sys

from .toile import main_urd as main

__all__ = ["main"]

if __name__ == "__main__":
    sys.exit(main())
