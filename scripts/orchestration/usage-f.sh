#!/bin/sh
# Token + cost table for the follow-up slice (F1, F3). Add session ids as they start.
cd "$(dirname "$0")/../.." && exec python3 scripts/orchestration/usage.py \
  orchestrator6=ses_e529b769dffek0Gq502nVntPe4 "$@"
