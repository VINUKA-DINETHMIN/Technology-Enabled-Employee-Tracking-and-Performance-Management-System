from __future__ import annotations

from pathlib import Path
import sys

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from C4_productivity_prediction.src.efficiency_window import launch_efficiency_window


if __name__ == "__main__":
    launch_efficiency_window()
