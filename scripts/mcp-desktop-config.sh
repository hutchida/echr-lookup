#!/usr/bin/env bash
# Print the Claude Desktop `mcpServers` snippet for THIS checkout, with absolute paths.
#   scripts/mcp-desktop-config.sh            # snippet on stdout, notes on stderr
# Paste the "echr-lookup" entry into ~/Library/Application Support/Claude/claude_desktop_config.json
# (see docs/mcp-setup.md). Reads only DATABASE_URL and DATA_SOURCE from the repo .env, never sources
# it, and never prints a password it cannot vouch for: see below.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
uv_path="$(command -v uv || true)"
if [ -z "$uv_path" ]; then
  echo "uv not found on PATH: install it first (https://docs.astral.sh/uv/)." >&2
  exit 1
fi

env_value() { # env_value KEY: the value of KEY in the repo .env (no quotes), or empty
  [ -f "$repo/.env" ] || return 0
  grep -E "^[[:space:]]*$1=" "$repo/.env" | tail -n 1 | sed -E "s/^[[:space:]]*$1=//; s/^[\"']//; s/[\"']\$//" || true
}

database_url="$(env_value DATABASE_URL)"
data_source="$(env_value DATA_SOURCE)"
data_source="${data_source:-snapshot}"

REPO="$repo" UV_PATH="$uv_path" DATABASE_URL="$database_url" DATA_SOURCE="$data_source" python3 - <<'PY'
import json
import os
import re
import sys

url = os.environ["DATABASE_URL"]
masked = False
# The project's local database uses the public compose.yaml password "echr". Any other password
# is treated as a secret and replaced, so this output is always safe to paste into a chat or a doc.
match = re.match(r"^(\w+://[^:/@]+):([^@]*)@(.*)$", url)
if match and match.group(2) != "echr":
    url = f"{match.group(1)}:***@{match.group(3)}"
    masked = True

env = {"DATA_SOURCE": os.environ["DATA_SOURCE"]}
if url:
    env["DATABASE_URL"] = url
snippet = {
    "mcpServers": {
        "echr-lookup": {
            "command": os.environ["UV_PATH"],
            "args": [
                "run", "--frozen", "--directory", os.path.join(os.environ["REPO"], "py"),
                "--group", "ml", "python", "-m", "echr_mcp", "--transport", "stdio",
            ],
            "env": env,
        }
    }
}
print(json.dumps(snippet, indent=2))
if masked:
    print(
        "note: the DATABASE_URL password was hidden as ***. The server also reads DATABASE_URL "
        "from the repo .env, so you can delete the DATABASE_URL line above.",
        file=sys.stderr,
    )
if not url:
    print("note: no DATABASE_URL in .env; the server falls back to the local default.", file=sys.stderr)
PY
