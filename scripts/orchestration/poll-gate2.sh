#!/bin/sh
# Gate 2 poll: wait up to $1 seconds for mail, then show the last 2 lines of each ACTIVE worker.
# Edit the list as dispatches change (I1-I3 done; A1 answer-first running).
cd "$(dirname "$0")/../.." && POLL_LINES="${POLL_LINES:-2}" exec python3 scripts/orchestration/poll.py "${1:-180}" \
  A1=ctx_f9a433edbcbc
