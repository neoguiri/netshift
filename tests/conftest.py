import os
import sys
from pathlib import Path

# Les tests vérifient les messages en français (langue source), quelle que soit la langue du poste ou de la CI.
os.environ["NETSHIFT_LANG"] = "fr"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
