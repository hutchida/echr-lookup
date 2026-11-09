#!/bin/sh
# Token + cost table for every agent session in the MCP slice (reads opencode session export).
cd "$(dirname "$0")/../.." && exec python3 scripts/orchestration/usage.py \
  orchestrator4=ses_e579d1058ffe7fiiTqo0k7lgWX check_opus=ses_e579ca5e5ffeYAveyzI3OlYS7w check_sonnet=ses_e579ca5e8ffeTB8icGxhk3rcqO \
  W0=ses_e5798b534ffePddhFoTxDNayCB \
  M1=ses_e57844073ffe6vVkmMQK22dTuN M2=ses_e5784396cffeEFPljyY4An4lH9 M3=ses_e57843262ffeJjp8xr6w0gUWRm "$@"
