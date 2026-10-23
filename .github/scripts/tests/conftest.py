import sys
from pathlib import Path

# The checks live one directory up and are plain scripts, not an installable package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
