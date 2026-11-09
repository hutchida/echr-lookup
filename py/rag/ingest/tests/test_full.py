import json
from urllib.parse import parse_qs, urlparse

import pytest

from rag.contract import contract_errors
from rag.ingest import HudocBlocked, RequestCapReached, run_ingest
from rag.ingest.full import FullDownloader, ListingLoopError
from rag.ingest.hudoc import (
    LISTING_QUERIES,
    HudocClient,
    RawResponse,
    entry_from_row,
    looks_like_challenge,
    normalise_outcome,
)
from rag.ingest.ratelimit import RateLimiter

from .fakes import FakeClock, FakeConn, FakeDb, FakeHudoc, hudoc_row


def make_client(tmp_path, transport, clock, **limiter_kw):
    limiter = RateLimiter(tmp_path, clock=clock.time, sleep=clock.sleep, **limiter_kw)
    return HudocClient(transport, limiter, tmp_path / "hudoc-requests.jsonl", clock=clock.time)


def rows(n, doctype="HEJUD", offset=0):
    return [hudoc_row(offset + i, doctype) for i in range(n)]


def fake_get(url: str) -> bytes:
    return b"<act>Human Rights Act</act>" * 100


def ingest(tmp_path, client, **kw):
    lines: list[str] = []
    snap = tmp_path / "snap"
    (snap / "legislation").mkdir(parents=True, exist_ok=True)
    (snap / "legislation" / "echr-convention.txt").write_text("ARTICLE 1\n" * 100)
    db = kw.pop("db", None) or FakeDb()
    run = run_ingest(
        FakeConn(),
        "full",
        deps=db.deps(),
        client=client,
        full_root=tmp_path / "full",
        snapshot_root=snap,
        http_get=fake_get,
        out=lines.append,
        **kw,
    )
    return run, lines, db


def test_listing_uses_the_documented_uk_english_queries():
    queries = dict(LISTING_QUERIES)
    for name, code in {
        "judgments": "HEJUD",
        "decisions": "HEDEC",
        "communicated": "HECOM",
        "legal_summaries": "CLIN",
    }.items():
        assert f'(doctype:"{code}")' in queries[name]
        assert queries[name].startswith(
            'contentsitename=ECHR AND (respondent:"GBR") AND (languageisocode:"ENG")'
        )
    assert not any("RES" in q for q in queries.values())  # no Committee of Ministers resolutions
    assert not any("HEREP" in q for q in queries.values())  # Commission reports are skipped


def test_challenge_detection():
    assert looks_like_challenge(RawResponse(403, b"x"))
    assert looks_like_challenge(RawResponse(200, b"<title>Just a moment...</title>"))
    assert looks_like_challenge(RawResponse(200, b"ok", cf_mitigated="challenge"))
    assert looks_like_challenge(RawResponse(429, b"slow down"))
    assert looks_like_challenge(RawResponse(200, b'{"resultcount": 1}')) is None
    # seen live: ordinary documents embed Cloudflare's passive jsd script; that is NOT a challenge
    jsd = b"<style></style><p>1. Text.</p><script>'/cdn-cgi/challenge-platform/scripts/jsd/main.js'"
    assert looks_like_challenge(RawResponse(200, jsd)) is None
    assert (
        looks_like_challenge(RawResponse(200, b"<p>Wait just a moment, said the judge.</p>"))
        is None
    )


def test_listing_row_becomes_valid_manifest_entry():
    for doctype in ("HEJUD", "HEDEC", "HECOM", "CLIN"):
        e = entry_from_row(
            hudoc_row(1, doctype), sha256="a" * 64, retrieved_at="2026-11-03T10:00:00Z"
        )
        assert contract_errors("ManifestEntry", e) == [], doctype
    e = entry_from_row(hudoc_row(1), sha256="a" * 64, retrieved_at="2026-11-03T10:00:00Z")
    assert e["case_name"] == "TEST 1 v. THE UNITED KINGDOM"
    assert e["articles"] == ["3", "8-1"] and e["application_numbers"] == ["1/01", "1/02"]
    assert e["outcome"] == "violation" and e["importance"] == 2 and e["date"] == "2010-05-04"
    com = entry_from_row(
        hudoc_row(2, "HECOM"), sha256="a" * 64, retrieved_at="2026-11-03T10:00:00Z"
    )
    assert com["outcome"] == "not_applicable"
    assert normalise_outcome("Inadmissible") == "inadmissible"


def test_full_mode_end_to_end_with_limit(tmp_path):
    clock = FakeClock()
    transport = FakeHudoc({"HEJUD": rows(10)})
    client = make_client(tmp_path / "full", transport, clock)
    run, lines, db = ingest(tmp_path, client, limit=3)
    assert contract_errors("IngestRun", run) == []
    assert run["data_source"] == "full"
    # 3 HUDOC documents + the Human Rights Act + the Convention
    assert run["counts"]["seen"] == 5 and run["counts"]["new"] == 5
    # 1 listing request (length=3) + 3 bodies + 1 count of the skipped Commission reports
    assert len(transport.urls) == 5
    assert "length=3" in transport.urls[0]
    assert "HEREP" in transport.urls[-1] and "length=1" in transport.urls[-1]
    manifest = json.loads((tmp_path / "full" / "manifest.json").read_text())
    assert all(contract_errors("ManifestEntry", e) == [] for e in manifest)
    assert {e["data_source"] for e in manifest} == {"full"}
    log = [
        json.loads(x) for x in (tmp_path / "full" / "hudoc-requests.jsonl").read_text().splitlines()
    ]
    assert len(log) == 5 and {r["status"] for r in log} == {200}


def test_requests_never_faster_than_one_per_second(tmp_path):
    clock = FakeClock()
    transport = FakeHudoc({"HEJUD": rows(8)})
    client = make_client(tmp_path / "full", transport, clock)
    ingest(tmp_path, client, limit=8)
    stats = client.stats()
    assert stats["requests"] == 10  # listing + 8 bodies + report count
    assert stats["min_gap_seconds"] >= 1.05 - 1e-6
    assert stats["mean_rate_per_second"] <= 1.0


def test_challenge_stops_cleanly_and_next_run_resumes(tmp_path):
    clock = FakeClock()
    all_rows = {"HEJUD": rows(6)}
    blocked = FakeHudoc(all_rows, block_after=4)  # listing + 3 bodies, then a challenge
    client = make_client(tmp_path / "full", blocked, clock)
    with pytest.raises(HudocBlocked):
        ingest(tmp_path, client, limit=6)
    state = json.loads((tmp_path / "full" / "state.json").read_text())
    assert state["status"] == "blocked" and "cf-mitigated" in state["reason"]
    assert len(list((tmp_path / "full" / "hudoc").glob("*.html"))) == 3
    assert len(blocked.urls) == 5  # stopped at the first challenge, no further requests
    assert not any(p.suffix == ".part" for p in (tmp_path / "full").rglob("*"))

    # a human solves the check; the same command now resumes
    healthy = FakeHudoc(all_rows)
    client2 = make_client(tmp_path / "full", healthy, clock)
    run, _, db = ingest(tmp_path, client2, limit=6)
    body_urls = [u for u in healthy.urls if "conversion" in u]
    assert len(body_urls) == 3  # only the 3 missing documents are fetched
    assert run["counts"]["new"] == 6 + 2
    assert len(healthy.urls) == 4  # 3 bodies + the report count; the listing came from the cache


def test_second_full_run_downloads_nothing_and_skips_everything(tmp_path):
    clock = FakeClock()
    transport = FakeHudoc({"HEJUD": rows(4)})
    db = FakeDb()
    ingest(tmp_path, make_client(tmp_path / "full", transport, clock), limit=4, db=db)
    again = FakeHudoc({"HEJUD": rows(4)})
    run, _, _ = ingest(tmp_path, make_client(tmp_path / "full", again, clock), limit=4, db=db)
    assert run["counts"]["unchanged_skipped"] == 6 and run["counts"]["new"] == 0
    assert again.urls == []  # listing + report count cached, files on disk: zero HUDOC requests


def test_commission_reports_are_counted_not_ingested(tmp_path):
    clock = FakeClock()
    transport = FakeHudoc({"HEJUD": rows(2), "HEREP": rows(7, "HEREP", offset=300)})
    client = make_client(tmp_path / "full", transport, clock)
    run, lines, db = ingest(tmp_path, client)
    assert "skipped_commission_reports=7" in "\n".join(lines)
    assert set(run) == {
        "run_id",
        "data_source",
        "started_at",
        "finished_at",
        "stage_seconds",
        "counts",
        "embedder_model",
        "embedding_dim",
    }
    assert run["counts"]["seen"] == 4  # 2 judgments + 2 legislation: reports not counted
    assert not any(i.startswith("001-53") for i in db.hashes)
    assert [u for u in transport.urls if "conversion" in u and "id=001-53" in u] == []
    assert sum("HEREP" in u for u in transport.urls) == 1  # the single count request
    with pytest.raises(ValueError):
        entry_from_row(hudoc_row(1, "HEREP"), sha256="a" * 64, retrieved_at="2026-11-03T10:00:00Z")


def test_run_cap_stops_the_run_and_keeps_downloads(tmp_path):
    clock = FakeClock()
    transport = FakeHudoc({"HEJUD": rows(6)})
    client = make_client(tmp_path / "full", transport, clock, run_cap=3)
    with pytest.raises(RequestCapReached):
        ingest(tmp_path, client, limit=6)
    assert len(transport.urls) == 3
    assert len(list((tmp_path / "full" / "hudoc").glob("*.html"))) == 2


def test_listing_pages_of_500_across_doctypes(tmp_path):
    clock = FakeClock()
    transport = FakeHudoc({"HEJUD": rows(600), "HEDEC": rows(3, "HEDEC", offset=1000)})
    client = make_client(tmp_path / "full", transport, clock)
    dl = FullDownloader(tmp_path / "full", client, get=fake_get)
    listed = dl.list_rows()
    # judgments in two pages (500 + 100), decisions in one, then empty queries
    assert len(listed) == 603
    assert [u for u in transport.urls if "length=500" in u][:2]
    assert sum("start=500" in u for u in transport.urls) >= 1


# --- listing pager: HUDOC lists some items twice, so paging must follow HUDOC's offset ----------


def decisions_listing(tmp_path, transport):
    clock = FakeClock()
    client = make_client(tmp_path / "full", transport, clock)
    lines: list[str] = []
    dl = FullDownloader(tmp_path / "full", client, get=fake_get, out=lines.append, now=clock.time)
    return dl, lines


def decision_requests(transport):
    return [u for u in transport.urls if "HEDEC" in u]


def starts(transport):
    return [int(parse_qs(urlparse(u).query)["start"][0]) for u in decision_requests(transport)]


def dup_list(unique, dup_positions):
    """`unique` distinct rows, with rows repeated at the given positions of the HUDOC list."""
    listed = [hudoc_row(i, "HEDEC") for i in range(unique)]
    for pos, src in dup_positions:
        listed.insert(pos, listed[src])
    return listed


def decided_ids(listed_rows):
    return {r["itemid"] for r in listed_rows}


def test_pager_follows_hudoc_offset_when_pages_hold_duplicates(tmp_path):
    listed = dup_list(1000, [(300, 10), (499, 11), (500, 12), (900, 13)])  # 1004 listed
    transport = FakeHudoc({"HEDEC": listed})
    dl, lines = decisions_listing(tmp_path, transport)
    got = dl.list_rows()
    assert len(got) == 1000
    assert starts(transport) == [0, 500, 1000]  # offsets, not unique counts
    assert len(transport.urls) == 3 + 3  # + one empty page for each of the 3 other queries
    assert "[listing decisions] WARNING: 1000 unique of 1004 listed (4 duplicates)" in lines


def test_final_page_made_only_of_duplicates_terminates(tmp_path):
    # the real bug: the last 10 rows HUDOC lists were all seen already, so the unique count stalled
    listed = dup_list(1000, []) + [hudoc_row(i, "HEDEC") for i in range(5, 15)]
    transport = FakeHudoc({"HEDEC": listed})
    dl, lines = decisions_listing(tmp_path, transport)
    got = dl.list_rows()
    assert len(got) == 1000
    assert starts(transport) == [0, 500, 1000]
    warnings = [line for line in lines if "WARNING" in line]
    assert warnings == ["[listing decisions] WARNING: 1000 unique of 1010 listed (10 duplicates)"]
    cached = json.loads((tmp_path / "full" / "listing.json").read_text())["decisions"]
    assert cached["complete"] is True
    assert cached["next_start"] == 1010


def test_short_final_page(tmp_path):
    transport = FakeHudoc({"HEDEC": rows(1200, "HEDEC")})
    dl, lines = decisions_listing(tmp_path, transport)
    assert len(dl.list_rows()) == 1200
    assert starts(transport) == [0, 500, 1000]  # 500 + 500 + 200, no extra empty request
    assert not any("WARNING" in line for line in lines)


def test_resultcount_larger_than_rows_stops_on_empty_page(tmp_path):
    transport = FakeHudoc({"HEDEC": rows(600, "HEDEC")}, resultcount={"HEDEC": 700})
    dl, lines = decisions_listing(tmp_path, transport)
    assert len(dl.list_rows()) == 600
    assert starts(transport) == [0, 500, 600]  # the third answer is empty
    assert "[listing decisions] WARNING: 600 unique of 700 listed (100 duplicates)" in lines


def test_resultcount_larger_than_rows_with_server_repeating_itself(tmp_path):
    transport = FakeHudoc(
        {"HEDEC": rows(600, "HEDEC")}, resultcount={"HEDEC": 5000}, repeat_tail=10
    )
    dl, lines = decisions_listing(tmp_path, transport)
    assert len(dl.list_rows()) == 600
    # 500, 100, then two pages with nothing new: stop
    assert starts(transport) == [0, 500, 600, 610]
    assert any("WARNING" in line and "600 unique of 5000" in line for line in lines)


def test_request_cap_stops_a_pager_that_never_finishes(tmp_path):
    # one new row per answer and 10 listed: needs 10 requests, the cap is ceil(10/500) + 3 = 4
    transport = FakeHudoc({"HEDEC": rows(10, "HEDEC")}, max_page=1)
    dl, _ = decisions_listing(tmp_path, transport)
    with pytest.raises(ListingLoopError, match="stopped after 4 requests"):
        dl.list_rows()
    assert len(decision_requests(transport)) == 4
    cached = json.loads((tmp_path / "full" / "listing.json").read_text())["decisions"]
    assert len(cached["rows"]) == 4 and cached["next_start"] == 4  # progress is kept


def test_resume_from_an_old_cache_without_next_start(tmp_path):
    # the real run: 2522 unique rows cached, HUDOC lists 2532 (10 duplicates), no `next_start`
    listed = dup_list(2522, []) + [hudoc_row(i, "HEDEC") for i in range(100, 110)]
    full = tmp_path / "full"
    full.mkdir()
    old = {
        "judgments": {
            "rows": rows(3),
            "total": 3,
            "complete": True,
            "fetched_at": 1_000_000_000.0,
        },
        "decisions": {
            "rows": listed[:2522],
            "total": 2532,
            "complete": False,
            "fetched_at": 1_000_000_000.0,
        },
    }
    (full / "listing.json").write_text(json.dumps(old))
    transport = FakeHudoc({"HEDEC": listed})
    clock = FakeClock()
    clock.now = 1_000_000_100.0
    client = make_client(full, transport, clock)
    lines: list[str] = []
    dl = FullDownloader(full, client, get=fake_get, out=lines.append, now=clock.time)
    got = dl.list_rows()
    assert len([r for r in got if r["doctype"] == "HEDEC"]) == 2522
    assert starts(transport) == [2522]  # one request finishes the decisions listing
    assert len(transport.urls) == 1 + 2  # ... then communicated and legal summaries (empty pages)
    assert "[listing decisions] WARNING: 2522 unique of 2532 listed (10 duplicates)" in lines
    # and a further run asks HUDOC for no listing again
    again = FakeHudoc({"HEDEC": listed})
    FullDownloader(
        full, make_client(full, again, clock), get=fake_get, out=lines.append, now=clock.time
    ).list_rows()
    assert again.urls == []


def test_one_transport_hiccup_does_not_stop_a_full_run(tmp_path):
    from rag.ingest.hudoc import HudocTransportError

    class Flaky:
        def __init__(self, inner):
            self.inner = inner
            self.calls = 0
            self.refreshes = 0

        def fetch(self, url):
            self.calls += 1
            if self.calls == 4:  # the third body, once
                raise HudocTransportError("`orca eval --expression` failed: exit status 1")
            return self.inner.fetch(url)

        def refresh(self):
            self.refreshes += 1

    clock = FakeClock()
    flaky = Flaky(FakeHudoc({"HEJUD": rows(5)}))
    limiter = RateLimiter(tmp_path / "full", clock=clock.time, sleep=clock.sleep)
    client = HudocClient(
        flaky,
        limiter,
        tmp_path / "full" / "hudoc-requests.jsonl",
        clock=clock.time,
        sleep=clock.sleep,
        out=lambda line: None,
    )
    run, _, _ = ingest(tmp_path, client, limit=5)
    assert len(list((tmp_path / "full" / "hudoc").glob("*.html"))) == 5
    assert flaky.refreshes == 1
    log = [
        json.loads(x) for x in (tmp_path / "full" / "hudoc-requests.jsonl").read_text().splitlines()
    ]
    assert [(r["status"], r["retry"]) for r in log if r["status"] == -1] == [(-1, 0)]
    assert [r["retry"] for r in log if r["retry"]] == [1]
    assert client.stats()["min_gap_seconds"] >= 1.05 - 1e-6
    assert run["counts"]["failed"] == 0
