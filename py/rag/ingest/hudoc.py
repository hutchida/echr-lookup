"""HUDOC access, politely, through Orca's built-in browser tab.

HUDOC (https://hudoc.echr.coe.int) sits behind a Cloudflare managed challenge: plain HTTP clients
get 403. A real browser that has passed the challenge does not. So requests are same-origin
`fetch()` calls evaluated inside an Orca browser tab (`orca eval`), with our own limiter in front.

We never try to solve or get around the challenge. If a response looks like one (or like any other
block), `HudocBlocked` is raised and the run stops cleanly so a human can open the tab, complete
the check, and re-run.
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlencode

from .ratelimit import RateLimiter

BASE = "https://hudoc.echr.coe.int"
RANKING_MODEL = "11111111-0000-0000-0001-000000000001"
SELECT = (
    "itemid,docname,appno,doctype,doctypebranch,languageisocode,kpdate,respondent,"
    "article,conclusion,importance,ecli"
)
BASE_QUERY = 'contentsitename=ECHR AND (respondent:"GBR") AND (languageisocode:"ENG")'

# The exact UK English queries of docs/hudoc-measurement.md section 2 (Committee of Ministers
# resolutions are left out on purpose).
LISTING_QUERIES: list[tuple[str, str]] = [
    ("judgments", f'{BASE_QUERY} AND (doctype:"HEJUD")'),
    ("decisions", f'{BASE_QUERY} AND (doctype:"HEDEC")'),
    ("communicated", f'{BASE_QUERY} AND (doctype:"HECOM")'),
    ("legal_summaries", f'{BASE_QUERY} AND (doctype:"CLIN")'),
]

# Commission reports are NOT ingested: the contract's DocType has no value for them. We only count
# them (one `length=1` request) so the summary can say how many were skipped.
COMMISSION_REPORTS_QUERY = f'{BASE_QUERY} AND (doctype:"HEREP")'


# Seconds to wait before retry 1, 2, 3 of a transport-only failure (see HudocClient).
RETRY_BACKOFF: tuple[float, ...] = (5.0, 15.0, 45.0)

BLOCK_INSTRUCTIONS = (
    "HUDOC did not give us a normal answer ({reason}).\n"
    "Nothing was lost: downloaded files and the listing are saved and the next run resumes.\n"
    "What to do: open the HUDOC tab in Orca's built-in browser (https://hudoc.echr.coe.int/eng),\n"
    "complete any check the page shows, wait until the normal search page appears, then run the\n"
    "same command again. This program never tries to solve or bypass the check itself."
)


class HudocBlocked(RuntimeError):
    """A challenge page, a 403 or a 429: stop and ask a human."""


class HudocUnavailable(RuntimeError):
    """The browser route itself is unusable (no `orca`, no tab, eval failed)."""


class HudocTransportError(HudocUnavailable):
    """A one-off hiccup of the browser route (`orca` exited non-zero or timed out, or its output
    was unparseable). The only failure `HudocClient` retries; a block is never retried."""


@dataclass
class RawResponse:
    status: int
    body: bytes
    content_type: str = ""
    secs: float = 0.0
    cf_mitigated: str | None = None
    retry_after: str | None = None


class Transport(Protocol):
    def fetch(self, url: str) -> RawResponse: ...


def looks_like_challenge(resp: RawResponse) -> str | None:
    """Reason string if this response is a block/challenge, else None."""
    if resp.cf_mitigated:
        return f"Cloudflare header cf-mitigated: {resp.cf_mitigated}"
    if resp.status in (403, 429, 503):
        return f"HTTP {resp.status}"
    head = resp.body[:30000].lower()
    # Real documents also carry Cloudflare's passive "jsd" script (/cdn-cgi/challenge-platform/
    # scripts/jsd/...), so that path alone proves nothing. These markers belong to the challenge
    # page itself.
    for marker, what in (
        (b"<title>just a moment", "challenge page ('Just a moment...')"),
        (b"cf_chl_opt", "challenge page (cf_chl_opt)"),
        (b"/orchestrate/chl_page", "challenge page (orchestrate script)"),
        (b"enable javascript and cookies to continue", "challenge page (enable cookies)"),
    ):
        if marker in head:
            return what
    return None


_JS = """(async()=>{const t0=performance.now();
const r=await fetch(%(url)s,{headers:{'Accept':'*/*'}});
const b=new Uint8Array(await r.arrayBuffer());let s='';
for(let i=0;i<b.length;i+=32768)s+=String.fromCharCode.apply(null,b.subarray(i,i+32768));
return JSON.stringify({status:r.status,ctype:r.headers.get('content-type'),
  secs:(performance.now()-t0)/1000,cf:r.headers.get('cf-mitigated'),
  retry:r.headers.get('retry-after'),b64:btoa(s)})})()"""


def _orca_json(args: list[str], timeout: float = 180) -> dict:
    try:
        proc = subprocess.run(
            ["orca", *args, "--json"], capture_output=True, text=True, timeout=timeout, check=True
        )
    except FileNotFoundError as exc:
        raise HudocUnavailable("the `orca` command was not found on PATH") from exc
    except subprocess.SubprocessError as exc:
        raise HudocTransportError(f"`orca {' '.join(args[:2])}` failed: {exc}") from exc
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise HudocTransportError(
            f"`orca {' '.join(args[:2])}` printed unparseable output: {proc.stdout[:200]!r}"
        ) from exc


def _find_page_id(tab: dict) -> str | None:
    for key in ("browserPageId", "pageId", "page", "id"):
        if isinstance(tab.get(key), str):
            return tab[key]
    return None


def find_hudoc_page(list_tabs: Callable[[], dict] | None = None) -> str | None:
    """Page id of an open tab on hudoc.echr.coe.int, or None."""
    data = (list_tabs or (lambda: _orca_json(["tab", "list"])))()
    tabs = data.get("result", {}).get("tabs", [])
    for tab in tabs:
        if str(tab.get("url", "")).startswith(BASE):
            return _find_page_id(tab)
    return None


class OrcaTransport:
    """fetch() inside an Orca browser tab on HUDOC (found with `orca tab list`, else created)."""

    def __init__(self, page_id: str | None = None) -> None:
        self.page_id = page_id

    def ensure_page(self) -> str:
        if self.page_id:
            return self.page_id
        page = find_hudoc_page()
        if page is None:
            _orca_json(["tab", "create", "--url", f"{BASE}/eng"])
            for _ in range(20):
                time.sleep(1.5)
                page = find_hudoc_page()
                if page:
                    break
        if page is None:
            raise HudocUnavailable(
                "no HUDOC tab found in Orca (`orca tab list --json`) and creating one failed"
            )
        self.page_id = page
        return page

    def refresh(self) -> None:
        """Before a retry: look the HUDOC tab up again (its page id may have changed). With no tab
        left, forget the id so `ensure_page` recreates the tab as on a first run."""
        try:
            self.page_id = find_hudoc_page()
        except HudocUnavailable:
            self.page_id = None

    def fetch(self, url: str) -> RawResponse:
        page = self.ensure_page()
        expr = _JS % {"url": json.dumps(url)}
        out = _orca_json(["eval", "--expression", expr, "--page", page])
        try:
            res = json.loads(out["result"]["result"])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise HudocTransportError(f"unexpected `orca eval` output: {str(out)[:200]}") from exc
        return RawResponse(
            status=res["status"],
            body=base64.b64decode(res["b64"]),
            content_type=res.get("ctype") or "",
            secs=res.get("secs", 0.0),
            cf_mitigated=res.get("cf"),
            retry_after=res.get("retry"),
        )


class HudocClient:
    """Limiter + request log + block detection + transport-only retries in front of a `Transport`.

    A `HudocTransportError` (the browser route hiccupped) is retried up to `len(backoff)` times,
    waiting `backoff[i]` seconds first and asking the transport to re-find its tab (`refresh()`).
    Every retry is a new attempt: it passes the limiter again and gets its own log row.
    A block (`HudocBlocked`) is never retried.
    """

    def __init__(
        self,
        transport: Transport,
        limiter: RateLimiter,
        log_path: Path,
        *,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        backoff: tuple[float, ...] = RETRY_BACKOFF,
        out: Callable[[str], None] = print,
    ) -> None:
        self.transport = transport
        self.limiter = limiter
        self.log_path = Path(log_path)
        self.clock = clock
        self.sleep = sleep
        self.backoff = backoff
        self.out = out
        self.starts: list[float] = []

    def get(self, path: str, params: dict | None = None, *, tag: str = "") -> RawResponse:
        url = path + ("?" + urlencode(params) if params else "")
        retry = 0
        while True:
            try:
                resp = self._attempt(url, tag, retry)
                break
            except HudocTransportError as exc:
                if retry >= len(self.backoff):
                    raise
                wait = self.backoff[retry]
                retry += 1
                self.out(
                    f"[retry {retry}/{len(self.backoff)}] orca eval failed ({exc}); "
                    f"waiting {wait:g} s"
                )
                self.sleep(wait)
                refresh = getattr(self.transport, "refresh", None)
                if refresh:
                    refresh()
        reason = looks_like_challenge(resp)
        if reason:
            raise HudocBlocked(reason)
        return resp

    def _attempt(self, url: str, tag: str, retry: int) -> RawResponse:
        n = self.limiter.acquire()
        started = self.clock()
        self.starts.append(started)
        t0 = time.perf_counter()
        resp: RawResponse | None = None
        try:
            resp = self.transport.fetch(url)
        finally:
            self._log(n, url, tag, resp, started, time.perf_counter() - t0, retry)
        return resp

    def _log(
        self,
        n: int,
        url: str,
        tag: str,
        resp: RawResponse | None,
        started: float,
        wall: float,
        retry: int = 0,
    ) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "n": n,
            "t": started,
            "url": url[:300],
            "tag": tag,
            "status": resp.status if resp else -1,
            "bytes": len(resp.body) if resp else 0,
            "secs": round(resp.secs, 4) if resp else 0,
            "wall": round(wall, 4),
            "retry": retry,
        }
        with open(self.log_path, "a") as f:
            f.write(json.dumps(row) + "\n")

    def search(self, query: str, *, start: int, length: int, tag: str = "listing") -> dict:
        params = {
            "query": query,
            "select": SELECT,
            "sort": "kpdate Descending",
            "start": start,
            "length": length,
            "rankingModelId": RANKING_MODEL,
        }
        resp = self.get("/app/query/results", params, tag=tag)
        try:
            return json.loads(resp.body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise HudocBlocked("search answer was not JSON") from exc

    def body(self, item_id: str) -> bytes:
        resp = self.get(
            "/app/conversion/docx/html/body", {"library": "ECHR", "id": item_id}, tag="body"
        )
        if resp.status != 200 or len(resp.body) < 1000:
            raise DocumentUnavailable(f"{item_id}: HTTP {resp.status}, {len(resp.body)} bytes")
        return resp.body

    def stats(self) -> dict:
        gaps = [b - a for a, b in zip(self.starts, self.starts[1:], strict=False)]
        span = self.starts[-1] - self.starts[0] if len(self.starts) > 1 else 0.0
        return {
            "requests": len(self.starts),
            "min_gap_seconds": round(min(gaps), 3) if gaps else None,
            "mean_rate_per_second": round((len(self.starts) - 1) / span, 3) if span > 0 else None,
        }


class DocumentUnavailable(RuntimeError):
    """One document could not be downloaded (not a challenge): count it as failed, carry on."""


# --- listing row -> ManifestEntry ------------------------------------------------------------


def normalise_outcome(conclusion: str | None) -> str:
    c = conclusion or ""
    viol = bool(re.search(r"(?<![Nn]o )(?<![Nn]on-)\b[Vv]iolation of", c))
    noviol = bool(re.search(r"\b[Nn]o violation", c))
    if viol and noviol:
        return "mixed"
    if viol:
        return "violation"
    if noviol:
        return "no_violation"
    if re.match(r"(?i)partly (admissible|inadmissible|struck)", c):
        return "partly_inadmissible"
    if re.match(r"(?i)inadmissible", c):
        return "inadmissible"
    if re.match(r"(?i)struck out", c):
        return "struck_out"
    if re.match(r"(?i)admissible", c):
        return "admissible"
    return "other"


METADATA_GROUNDS = [
    (r"manifestly ill-founded", "manifestly_ill_founded"),
    (r"exhaustion of domestic remedies", "non_exhaustion"),
    (r"six-month|six month", "out_of_time"),
    (r"ratione materiae", "incompatible_ratione_materiae"),
    (r"ratione personae", "incompatible_ratione_personae"),
    (r"ratione temporis", "incompatible_ratione_temporis"),
    (r"ratione loci", "incompatible_ratione_loci"),
    (r"abuse of", "abuse_of_right"),
    (r"no significant disadvantage", "no_significant_disadvantage"),
    (r"matter already examined|substantially the same", "substantially_same"),
    (r"\(art\. 34\) victim|article 34 - victim", "not_a_victim"),
]


def metadata_grounds(conclusion: str | None) -> list[str] | None:
    """Grounds HUDOC's own `conclusion` names for an inadmissibility, else None."""
    if not conclusion or "nadmissible" not in conclusion:
        return None
    found: list[str] = []
    in_inadmissible = False
    for part in (p.strip() for p in conclusion.split(";")):
        starts = bool(
            re.match(
                r"(?i)(partly )?(remainder )?inadmissible|partly (admissible;)?inadmissible", part
            )
        )
        if starts:
            in_inadmissible = True
        elif not part.startswith("("):
            in_inadmissible = False
        if starts or (in_inadmissible and part.startswith("(")):
            for pat, ground in METADATA_GROUNDS:
                if re.search(pat, part, re.I) and ground not in found:
                    found.append(ground)
    return found or None


DOC_TYPES = {
    "HEJUD": "judgment",
    "HEDEC": "decision",
    "HECOM": "communicated",
    "CLIN": "legal_summary",
}


def _chamber(branch: str | None) -> str | None:
    if branch in ("GRANDCHAMBER", "DECGRANDCHAMBER"):
        return "Grand Chamber"
    if branch in ("CHAMBER", "ADMISSIBILITY"):
        return "Chamber"
    if branch in ("COMMITTEE", "ADMISSIBILITYCOM"):
        return "Committee"
    return None


def entry_from_row(row: dict, *, sha256: str, retrieved_at: str) -> dict:
    """One HUDOC listing row (`columns`) + the stored file's hash -> ManifestEntry dict."""
    doctype = row["doctype"]
    if doctype not in DOC_TYPES:
        raise ValueError(f"unexpected doctype {doctype!r}")
    date = (row.get("kpdate") or "")[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ValueError(f"unusable kpdate {row.get('kpdate')!r}")
    conclusion = row.get("conclusion") or None
    grounds = metadata_grounds(conclusion)
    item_id = row["itemid"]
    return {
        "item_id": item_id,
        "case_name": re.sub(r"^CASE OF ", "", row.get("docname") or item_id)[:300],
        "application_numbers": [a for a in (row.get("appno") or "").split(";") if a],
        "ecli": row.get("ecli") or None,
        "doc_type": DOC_TYPES[doctype],
        "chamber": _chamber(row.get("doctypebranch")),
        "date": date,
        "articles": [a for a in (row.get("article") or "").split(";") if a],
        "outcome_raw": conclusion,
        "outcome": "not_applicable" if doctype == "HECOM" else normalise_outcome(conclusion),
        "inadmissibility_grounds": grounds,
        "inadmissibility_grounds_source": "metadata" if grounds else None,
        "importance": int(row["importance"]) if (row.get("importance") or "").isdigit() else None,
        "language": "en",
        "source_url": f"{BASE}/eng?i={item_id}",
        "sha256": sha256,
        "data_source": "full",
        "retrieved_at": retrieved_at,
        "format": "html",
        "path": f"hudoc/{item_id}.html",
    }
