"""Manual sync from the command line (the dashboard process syncs daily by itself).

    python scheduler.py            # all active cabinets, incremental
    python scheduler.py 3 2026-09-01 2026-09-30   # one cabinet, explicit period
"""

import logging
import sys
from datetime import date

from core.db import init_db
from sync.runner import sync_all, sync_cabinet

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

if __name__ == "__main__":
    init_db()
    if len(sys.argv) >= 2:
        args = sys.argv[1:]
        d0 = date.fromisoformat(args[1]) if len(args) > 1 else None
        d1 = date.fromisoformat(args[2]) if len(args) > 2 else None
        print(sync_cabinet(int(args[0]), d0, d1))
    else:
        sync_all()
