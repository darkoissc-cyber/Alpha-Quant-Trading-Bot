import pytest
from datetime import datetime, timezone, timedelta
from typing import List

from alpha_platform.config.settings import settings
from alpha_platform.market_data.news_filter import (
    NewsFilter,
    NewsEvent,
    NewsImpact,
    BaseNewsProvider,
)
from alpha_platform.risk_engine.python_binding import RiskEngine


class MockNewsProvider(BaseNewsProvider):
    def __init__(self, events: List[NewsEvent] = None, should_raise: bool = False):
        self.events = events if events is not None else []
        self.should_raise = should_raise

    def fetch_events(self) -> List[NewsEvent]:
        if self.should_raise:
            raise RuntimeError("API Timeout / Provider Connection Refused")
        return self.events


def test_high_impact_event_blocks_entry():
    now = datetime.now(timezone.utc)
    nfp_event = NewsEvent(
        event_id="US_NFP_001",
        currency="USD",
        title="Non-Farm Payrolls",
        impact=NewsImpact.HIGH,
        event_time_utc=now + timedelta(minutes=10),
        forecast="180K",
        previous="150K",
        source="TestMock"
    )
    provider = MockNewsProvider(events=[nfp_event])
    news_filter = NewsFilter(provider=provider)

    # Test EURUSD (contains USD) within 30-min window
    blocked, reason = news_filter.is_news_blocked("EURUSD", current_time_utc=now)
    assert blocked is True
    assert "Non-Farm Payrolls" in reason

    # Test XAUUSD (contains USD)
    blocked_gold, _ = news_filter.is_news_blocked("XAUUSD", current_time_utc=now)
    assert blocked_gold is True

    # Test EURGBP (does NOT contain USD)
    blocked_eurgbp, _ = news_filter.is_news_blocked("EURGBP", current_time_utc=now)
    assert blocked_eurgbp is False


def test_medium_and_low_impact_events_ignored():
    now = datetime.now(timezone.utc)
    med_event = NewsEvent(
        event_id="EUR_MED_001",
        currency="EUR",
        title="German Import Price Index",
        impact=NewsImpact.MEDIUM,
        event_time_utc=now + timedelta(minutes=5),
        source="TestMock"
    )
    low_event = NewsEvent(
        event_id="USD_LOW_001",
        currency="USD",
        title="API Crude Oil Stock Change",
        impact=NewsImpact.LOW,
        event_time_utc=now + timedelta(minutes=5),
        source="TestMock"
    )
    provider = MockNewsProvider(events=[med_event, low_event])
    news_filter = NewsFilter(provider=provider)

    blocked, _ = news_filter.is_news_blocked("EURUSD", current_time_utc=now)
    assert blocked is False


def test_currency_mapping():
    currencies_eurusd = NewsFilter.get_symbol_currencies("EURUSDm")
    assert "EUR" in currencies_eurusd and "USD" in currencies_eurusd

    currencies_gold = NewsFilter.get_symbol_currencies("XAUUSD.c")
    assert currencies_gold == ["USD"]

    currencies_gbpjpy = NewsFilter.get_symbol_currencies("GBPJPY")
    assert "GBP" in currencies_gbpjpy and "JPY" in currencies_gbpjpy

    currencies_btc = NewsFilter.get_symbol_currencies("BTCUSD")
    assert currencies_btc == ["USD"]


def test_empty_calendar():
    provider = MockNewsProvider(events=[])
    news_filter = NewsFilter(provider=provider)
    now = datetime.now(timezone.utc)

    blocked, reason = news_filter.is_news_blocked("EURUSD", current_time_utc=now)
    assert blocked is False
    assert reason is None


def test_provider_failure_policy():
    provider = MockNewsProvider(should_raise=True)
    news_filter = NewsFilter(provider=provider)
    now = datetime.now(timezone.utc)

    # With FAIL_SAFE_NEWS = False, error allows trading with log warning
    settings.FAIL_SAFE_NEWS = False
    blocked, _ = news_filter.is_news_blocked("EURUSD", current_time_utc=now)
    assert blocked is False

    # With FAIL_SAFE_NEWS = True, error blocks trading safely
    settings.FAIL_SAFE_NEWS = True
    blocked_fail_safe, reason = news_filter.is_news_blocked("EURUSD", current_time_utc=now)
    assert blocked_fail_safe is True
    assert "Fail-Safe Active" in reason

    # Restore default
    settings.FAIL_SAFE_NEWS = False


def test_multiple_simultaneous_events():
    now = datetime.now(timezone.utc)
    ecb_rate = NewsEvent(
        event_id="ECB_001",
        currency="EUR",
        title="ECB Interest Rate Decision",
        impact=NewsImpact.HIGH,
        event_time_utc=now + timedelta(minutes=15),
        source="TestMock"
    )
    us_cpi = NewsEvent(
        event_id="CPI_001",
        currency="USD",
        title="US Consumer Price Index",
        impact=NewsImpact.HIGH,
        event_time_utc=now + timedelta(minutes=15),
        source="TestMock"
    )
    provider = MockNewsProvider(events=[ecb_rate, us_cpi])
    news_filter = NewsFilter(provider=provider)

    blocked, reason = news_filter.is_news_blocked("EURUSD", current_time_utc=now)
    assert blocked is True
    assert "ECB" in reason or "US Consumer Price Index" in reason


def test_risk_engine_news_integration():
    now = datetime.now(timezone.utc)
    fed_decision = NewsEvent(
        event_id="FOMC_001",
        currency="USD",
        title="FOMC Rate Decision",
        impact=NewsImpact.HIGH,
        event_time_utc=now + timedelta(minutes=5),
        source="TestMock"
    )
    provider = MockNewsProvider(events=[fed_decision])
    news_filter = NewsFilter(provider=provider)
    risk_engine = RiskEngine(initial_equity=10000.0, news_filter=news_filter)

    # Evaluate candidate during news window
    verdict = risk_engine.evaluate_candidate(
        symbol="XAUUSD",
        current_equity=10000.0,
        proposed_volume=1.0,
        entry_price=1950.0,
        stop_loss=1940.0,
        current_spread_pips=10.0
    )

    assert verdict.passed is False
    assert "News Veto" in verdict.veto_reason
    assert verdict.scaled_position_size == 0.0
