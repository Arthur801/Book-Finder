"""Makes the host package importable from the tests without installing it.

Why: the host program is a plain directory run by the forced SSH command, not an installed distribution, so the tests
put its parent on sys.path the same way the entry script does.
"""

import sys
from pathlib import Path

HOST_DIR = Path(__file__).resolve().parents[2] / "host"
if str(HOST_DIR) not in sys.path:
    sys.path.insert(0, str(HOST_DIR))
