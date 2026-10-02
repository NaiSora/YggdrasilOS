"""muninn — un des corbeaux d'Odin (voir yggdrasil.corbeaux)."""

import sys

from .corbeaux import main_muninn as main

__all__ = ["main"]

if __name__ == "__main__":
    sys.exit(main())
