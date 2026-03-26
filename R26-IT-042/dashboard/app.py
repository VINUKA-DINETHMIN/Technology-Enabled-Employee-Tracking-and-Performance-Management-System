"""
R26-IT-042 — Employee Activity Monitoring System
dashboard/app.py

Entry point for the Admin Panel (CustomTkinter desktop GUI).

Launch from command line:
    python dashboard/app.py          # Admin panel
    python main.py --admin           # Also opens admin panel

The old Flask web dashboard has been superseded by the
CustomTkinter admin_panel.py desktop application.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dashboard.admin_panel import launch_admin_panel
from common.database import MongoDBClient
from config.settings import settings


def main() -> None:
    db = MongoDBClient(uri=settings.MONGO_URI, db_name=settings.MONGO_DB_NAME)
    db.connect()
    launch_admin_panel(db=db)


if __name__ == "__main__":
    main()
