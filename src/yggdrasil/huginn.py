"""huginn — un des corbeaux d'Odin (voir yggdrasil.corbeaux)."""

import sys

from .corbeaux import main_huginn as main

__all__ = ["main"]

if __name__ == "__main__":
    sys.exit(main())
