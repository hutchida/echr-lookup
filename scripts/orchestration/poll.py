#!/usr/bin/env python3
"""One monitoring poll: wait up to N seconds for worker mail, then print a compact status.

Usage: python3 scripts/orchestration/poll.py <wait_seconds> <label>=<dispatch_id> [...]
Does NOT ack deliveries; the orchestrator acks after processing.
"""

import json
import os
import subprocess
import sys


def run_json(args: list[str]) -> list[dict]:
    out = subprocess.run(args, capture_output=True, text=True).stdout
    dec, i, objs = json.JSONDecoder(), 0, []
    while i < len(out):
        while i < len(out) and out[i].isspace():
            i += 1
        if i >= len(out):
            break
        try:
            obj, i = dec.raw_decode(out, i)
            objs.append(obj)
        except json.JSONDecodeError:
            nl = out.find("\n", i)
            i = len(out) if nl < 0 else nl + 1
    return objs


def main() -> None:
    wait_s = int(sys.argv[1])
    dispatches = dict(a.split("=", 1) for a in sys.argv[2:])
    objs = run_json(
        ["orca", "orchestration", "check", "--wait", "--types", "worker_done,escalation,question",
         "--timeout-ms", str(wait_s * 1000), "--json"]
    )
    res = (objs[-1] if objs else {}).get("result", {})
    msgs = res.get("messages") or []
    print(f"mail: count={res.get('count', 0)} delivery={res.get('deliveryId')} timedOut={res.get('timedOut')}")
    for m in msgs:
        print(f"  [{m.get('type')}] id={m.get('id')} from={m.get('from')} subject={m.get('subject')!r}")
        print("   ", (m.get("body") or "")[:1500].replace("\n", "\n    "))
    for label, did in dispatches.items():
        r = run_json(["orca", "orchestration", "worker-read", "--dispatch", did, "--json"])
        t = (r[-1] if r else {}).get("result", {}).get("terminal", {})
        tail = [ln.strip() for ln in t.get("tail", []) if ln.strip() and not set(ln.strip()) <= set("┃╹▀█⬝ ")]
        print(f"{label}: status={t.get('status')}")
        for ln in tail[-int(os.environ.get("POLL_LINES", "8")) :]:
            print("   ", ln[:160])


if __name__ == "__main__":
    main()
