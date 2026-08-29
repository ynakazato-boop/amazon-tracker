#!/bin/bash
# Triggered by the host crontab. Runs one frequency batch inside the running
# `tracker` container, one at a time (flock), and keeps a capped log.
#
#   ./run-cron.sh daily
#   ./run-cron.sh weekly
#   ./run-cron.sh monthly
#
set -u

FREQ="${1:?usage: run-cron.sh <frequency>}"
DIR="/home/ubuntu/amazon-tracker"
LOG="$DIR/cron.log"
LOCK="/tmp/amazon-tracker-run.lock"

# Keep the log from growing forever (~2MB cap)
if [ -f "$LOG" ] && [ "$(stat -c%s "$LOG" 2>/dev/null || echo 0)" -gt 2000000 ]; then
  tail -c 500000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

{
  echo "----------------------------------------------------------------------"
  echo "$(date -Is)  START  freq=$FREQ"
} >> "$LOG"

# Only one batch at a time. If another is still running, skip this tick.
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "$(date -Is)  SKIP   another batch is still running" >> "$LOG"
  exit 0
fi

# Safety net: clear any Chromium left over from a previous crashed batch.
docker exec tracker python -c "from src.scraper import _kill_stray_chrome; _kill_stray_chrome()" >> "$LOG" 2>&1

docker exec tracker python main.py --run "$FREQ" >> "$LOG" 2>&1
RC=$?

echo "$(date -Is)  END    freq=$FREQ  rc=$RC" >> "$LOG"
exit "$RC"
