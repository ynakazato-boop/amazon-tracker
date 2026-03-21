"""
Amazon Keyword Rank Tracker - Entry point

Usage:
  python main.py           # Start scheduler (runs indefinitely)
  python main.py --test    # Test mode: run 1 ASIN × 1 KW immediately
"""

import argparse
import logging
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("tracker.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


def run_test():
    import csv
    from pathlib import Path
    from src.database import init_db, insert_ranking, start_run_log, finish_run_log
    from src.scraper import run_checks_sync

    init_db()

    targets_csv = Path("config/targets.csv")
    targets = []
    with open(targets_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            targets.append({
                "asin": row["asin"].strip(),
                "keyword": row["keyword"].strip(),
                "note": row.get("note", "").strip(),
            })
            break  # Only 1 target in test mode

    if not targets:
        logger.error("No targets found in config/targets.csv")
        sys.exit(1)

    t = targets[0]
    logger.info(f"[TEST] Checking ASIN={t['asin']} keyword='{t['keyword']}'")

    log_id = start_run_log()
    results = run_checks_sync(targets)
    r = results[0]

    logger.info(f"[TEST] Result: rank={r.rank}, page={r.page}")
    insert_ranking(r.asin, r.keyword, r.rank, r.page, t["note"])
    finish_run_log(log_id, total=1, success=1, failed=0)
    logger.info("[TEST] Done. Check data/rankings.db for results.")


def run_scheduler():
    from src.scheduler import start_scheduler

    scheduler = start_scheduler()
    logger.info("Tracker running. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Amazon Keyword Rank Tracker")
    parser.add_argument("--test", action="store_true", help="Run a single test check immediately")
    args = parser.parse_args()

    if args.test:
        run_test()
    else:
        run_scheduler()
