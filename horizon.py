"""Command-line entry point for the Home Assistant horizon generator."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "custom_components" / "horizon_profile"))

from horizon import main


if __name__ == "__main__":
    main()
