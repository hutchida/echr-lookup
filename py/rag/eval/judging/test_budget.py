import pytest

from .budget import (
    SOFT_LIMIT_USD,
    CapExceeded,
    SpendGuard,
    estimate_call_usd,
    spent_from_cost_log,
)


def test_estimate_uses_opus_prices_from_config():
    # 400,000 chars -> 100,000 tokens in at $4/Mtok = $0.40; 10 paragraphs -> 700 tokens out at $20
    est = estimate_call_usd("claude-opus-5-5", 400_000, 10)
    assert est == pytest.approx(0.40 + 700 * 20 / 1e6)


def test_reserve_allows_up_to_the_cap_and_refuses_past_it():
    guard = SpendGuard(lambda: 7.50, cap=8.0)
    guard.reserve(0.49)
    with pytest.raises(CapExceeded):
        guard.reserve(0.02)  # 7.50 + 0.49 + 0.02 > 8.00


def test_release_frees_the_reservation():
    guard = SpendGuard(lambda: 7.0, cap=8.0)
    guard.reserve(0.9)
    with pytest.raises(CapExceeded):
        guard.reserve(0.5)
    guard.release(0.9)
    guard.reserve(0.5)


def test_guard_reads_spend_fresh_every_time():
    spent = [0.0]
    guard = SpendGuard(lambda: spent[0], cap=1.0)
    guard.reserve(0.4)
    guard.release(0.4)
    spent[0] = 0.8
    with pytest.raises(CapExceeded):
        guard.reserve(0.4)


def test_there_is_no_limit_by_default():
    assert SOFT_LIMIT_USD is None
    guard = SpendGuard(lambda: 1e9)
    guard.reserve(1e9)  # never refuses without a soft limit


def test_estimate_for_the_proxy_model_uses_its_list_price():
    # 400,000 chars -> 100,000 tokens in at $5/Mtok = $0.50; 10 paragraphs -> 700 out at $25/Mtok
    est = estimate_call_usd("vertex-ai-claude-opus-4.8", 400_000, 10)
    assert est == pytest.approx(0.50 + 700 * 25 / 1e6)


def test_spent_query_filters_on_the_relevance_prefix():
    class Conn:
        def execute(self, sql, params):
            self.sql, self.params = sql, params
            return self

        def fetchone(self):
            return (1.25,)

        def commit(self):
            pass

    conn = Conn()
    assert spent_from_cost_log(conn) == 1.25
    assert "request_id LIKE" in conn.sql and conn.params == ("relevance-%",)
