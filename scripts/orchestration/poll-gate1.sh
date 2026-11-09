#!/bin/sh
# Gate 1 poll: wait up to $1 seconds for mail, then show the last 2 lines of each ACTIVE worker.
# Edit the list as dispatches change (tidy-up: S2-fix + S1-retry running).
cd "$(dirname "$0")/../.." && POLL_LINES="${POLL_LINES:-2}" exec python3 scripts/orchestration/poll.py "${1:-180}" \
  S2f=ctx_d5a497339809
