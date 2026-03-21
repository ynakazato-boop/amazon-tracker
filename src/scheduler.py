"""
APScheduler-based scheduler.
- daily   → every day at 02:00 JST
- weekly  → every Monday at 02:00 JST
- monthly → 1st of every month at 02:00 JST
"""

import csv
import logging
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.database import init_db, insert_ranking, start_run_log, finish_run_log
from src.scraper import run_checks_sync

logger = logging.getLogger(__name__)

TARGETS_CSV = Path(__file__).parent.parent / "config" / "targets.csv"


def load_targets(frequency: str) -> list[dict]:
    targets = []
    with open(TARGETS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["frequency"].strip() == frequency:
                targets.append({
                    "asin": row["asin"].strip(),
                    "keyword": row["keyword"].strip(),
                    "note": row.get("note", "").strip(),
                })
    return targets


def _run_job(frequency: str):
    logger.info(f"=== Starting {frequency} job ===")
    targets = load_targets(frequency)
    if not targets:
        logger.info(f"No targets for frequency={frequency}")
        return

    log_id = start_run_log()
    success = 0
    failed = 0

    try:
        results = run_checks_sync(targets)
        for result, target in zip(results, targets):
            try:
                insert_ranking(
                    asin=result.asin,
                    keyword=result.keyword,
                    rank=result.rank,
                    page=result.page,
                    note=target.get("note", ""),
                )
                success += 1
            except Exception as e:
                logger.error(f"DB insert error: {e}")
                failed += 1
    except Exception as e:
        logger.error(f"Job error: {e}")
        failed += len(targets)

    finish_run_log(log_id, total=len(targets), success=success, failed=failed)
    logger.info(f"=== {frequency} job done: {success} ok, {failed} failed ===")


def run_daily():
    _run_job("daily")


def run_weekly():
    _run_job("weekly")


def run_monthly():
    _run_job("monthly")


def start_scheduler() -> BackgroundScheduler:
    init_db()
    scheduler = BackgroundScheduler(timezone="Asia/Tokyo")

    scheduler.add_job(run_daily,   CronTrigger(hour=2, minute=0, timezone="Asia/Tokyo"), id="daily")
    scheduler.add_job(lambda: _run_job("twice_daily"), CronTrigger(hour="8,20", minute=0, timezone="Asia/Tokyo"), id="twice_daily")
    scheduler.add_job(run_weekly,  CronTrigger(day_of_week="mon", hour=2, minute=0, timezone="Asia/Tokyo"), id="weekly")
    scheduler.add_job(lambda: _run_job("biweekly"), IntervalTrigger(weeks=2, timezone="Asia/Tokyo"), id="biweekly")
    scheduler.add_job(run_monthly, CronTrigger(day=1, hour=2, minute=0, timezone="Asia/Tokyo"), id="monthly")

    scheduler.start()
    logger.info("Scheduler started (daily=02:00, twice_daily=08:00&20:00, weekly=Mon 02:00, biweekly=every 2 weeks, monthly=1st 02:00 JST)")
    return scheduler
