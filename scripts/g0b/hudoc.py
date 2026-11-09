"""Throwaway G0b HUDOC client: one shared rate limiter (<=1 req/s across ALL processes) and a
persistent request counter (hard cap) so the task's politeness rules are enforced in code."""

from __future__ import annotations

import base64
import fcntl
import json
import subprocess
import time
from pathlib import Path

BASE = "https://hudoc.echr.coe.int"
MIN_INTERVAL = 1.05  # seconds between any two HUDOC requests, across processes
HARD_CAP = 1500
STATE_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "g0b"
STATE = STATE_DIR / "hudoc-state.json"
LOCK = STATE_DIR / "hudoc.lock"
LOG = STATE_DIR / "hudoc-requests.jsonl"


def _throttle() -> int:
    """Block until >=MIN_INTERVAL since the last request (any process); bump + return the count."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        st = json.loads(STATE.read_text()) if STATE.exists() else {"count": 0, "last": 0.0}
        if st["count"] >= HARD_CAP:
            raise RuntimeError(f"HUDOC request cap {HARD_CAP} reached")
        wait = st["last"] + MIN_INTERVAL - time.time()
        if wait > 0:
            time.sleep(wait)
        st["count"] += 1
        st["last"] = time.time()
        STATE.write_text(json.dumps(st))
        return st["count"]


class Resp:
    def __init__(self, status: int, body: bytes, secs: float, ctype: str) -> None:
        self.status_code, self.content, self.secs, self.content_type = status, body, secs, ctype
        self.text = body.decode("utf-8", "replace")

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}: {self.text[:200]}")


_JS = """(async()=>{const t0=performance.now();
const r=await fetch(%(url)s,{headers:{'Accept':'*/*'}});
const b=new Uint8Array(await r.arrayBuffer());let s='';
for(let i=0;i<b.length;i+=32768)s+=String.fromCharCode.apply(null,b.subarray(i,i+32768));
return JSON.stringify({status:r.status,ctype:r.headers.get('content-type'),secs:(performance.now()-t0)/1000,
  retry:r.headers.get('retry-after'),b64:btoa(s)})})()"""


class Hudoc:
    """HUDOC sits behind a Cloudflare managed challenge, so plain HTTP clients get 403. Requests
    are therefore issued with fetch() inside Orca's built-in browser tab that already passed the
    challenge (same-origin, so cookies apply). The limiter + counter still run here in Python."""

    def get(self, path: str, params: dict | None = None, tag: str = "") -> Resp:
        from urllib.parse import urlencode

        url = path + ("?" + urlencode(params) if params else "")
        n = _throttle()
        t0 = time.perf_counter()
        status, size, secs, ctype, retry = -1, 0, 0.0, "", None
        try:
            out = subprocess.run(
                ["orca", "eval", "--expression", _JS % {"url": json.dumps(url)}, "--json"],
                capture_output=True,
                text=True,
                timeout=180,
                check=True,
            ).stdout
            res = json.loads(json.loads(out)["result"]["result"])
            body = base64.b64decode(res["b64"])
            status, size, secs, ctype, retry = (
                res["status"],
                len(body),
                res["secs"],
                res["ctype"] or "",
                res["retry"],
            )
            return Resp(status, body, secs, ctype)
        finally:
            with open(LOG, "a") as f:
                f.write(
                    json.dumps(
                        {
                            "n": n,
                            "t": time.time(),
                            "url": url[:300],
                            "tag": tag,
                            "status": status,
                            "bytes": size,
                            "secs": round(secs, 4),
                            "wall": round(time.perf_counter() - t0, 4),
                            "retry_after": retry,
                        }
                    )
                    + "\n"
                )

    def search(
        self,
        query: str,
        select: str,
        start: int = 0,
        length: int = 20,
        sort: str = "",
        tag: str = "search",
    ) -> dict:
        params = {
            "query": query,
            "select": select,
            "sort": sort,
            "start": start,
            "length": length,
            "rankingModelId": "11111111-0000-0000-0001-000000000001",
        }
        r = self.get("/app/query/results", params, tag=tag)
        r.raise_for_status()
        return r.json()


def request_count() -> int:
    return json.loads(STATE.read_text())["count"] if STATE.exists() else 0
