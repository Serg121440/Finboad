"""Daily data sync scheduler — runs at 06:00 MSK."""

import logging
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from database.db import init_db
from normalizer import full_sync
from config import SCHEDULER_TIMEZONE, SCHEDULER_HOUR, SCHEDULER_MINUTE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def job():
    logger.info("Scheduled sync started")
    results = full_sync(days_back=7)
    logger.info(
        "Sync complete — WB: %d, Ozon: %d, GSheets: %d",
        results["wb"],
        results["ozon"],
        results["gsheets"],
    )


def main():
    init_db()

    logger.info("Running initial sync on startup...")
    full_sync(days_back=90)

    scheduler = BlockingScheduler(timezone=SCHEDULER_TIMEZONE)
    scheduler.add_job(
        job,
        CronTrigger(hour=SCHEDULER_HOUR, minute=SCHEDULER_MINUTE, timezone=SCHEDULER_TIMEZONE),
        id="daily_sync",
        name="Daily marketplace sync",
        misfire_grace_time=3600,
    )

    logger.info(
        "Scheduler started — daily sync at %02d:%02d %s",
        SCHEDULER_HOUR,
        SCHEDULER_MINUTE,
        SCHEDULER_TIMEZONE,
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    main()
