"""AppImage launcher: set import paths explicitly (python runs with -E -s)."""
import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(here, "app"), os.path.join(here, "site-packages")]
from linux_defender.app import main  # noqa: E402

sys.exit(main())
