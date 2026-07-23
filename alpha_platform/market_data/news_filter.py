import os
import abc
import json
import urllib.request
import urllib.error
import threading
from enum import Enum
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Tuple

from alpha_platform.config.settings import settings
from alpha_platform.config.logging_config import logger


class NewsImpact(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass
class NewsEvent:
    event_id: str
    currency: str
    title: str
    impact: NewsImpact
    event_time_utc: datetime
    forecast: Optional[str] = None
    previous: Optional[str] = None
    actual: Optional[str] = None
    source: str = "ForexFactory"


class BaseNewsProvider(abc.ABC):
    """
    Abstract Interface for Economic News Calendar Data Providers.
    Allows seamlessly swapping providers (ForexFactory, FinancialModelingPrep, TradingEconomics).
    """

    @abc.abstractmethod
    def fetch_events(self) -> List[NewsEvent]:
        """Fetch economic calendar events for the current/upcoming period."""
        pass


class ForexFactoryNewsProvider(BaseNewsProvider):
    """
    ForexFactory Economic Calendar Provider.
    Fetches JSON economic calendar feed via faireconomy.media mirror
    with 10-second HTTP timeout, class-level caching, persistent disk cache,
    and graceful exception handling.
    """

    PRIMARY_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    DISK_CACHE_PATH = os.path.join("logs", "news_calendar_cache.json")
    
    # Shared class-level cache to prevent HTTP 429 rate-limiting across instances
    _shared_cache_events: List[NewsEvent] = []
    _shared_cache_time: Optional[datetime] = None
    _cache_ttl_seconds: int = 900  # 15 minutes memory cache

    def __init__(self, timeout_seconds: int = 10):
        self.timeout_seconds = timeout_seconds

    def _parse_raw_items(self, raw_data: List[Dict]) -> List[NewsEvent]:
        events: List[NewsEvent] = []
        for item in raw_data:
            try:
                currency = item.get("country", "").upper()
                title = item.get("title", "Economic Event")
                impact_raw = str(item.get("impact", "")).upper()

                if "HIGH" in impact_raw or impact_raw == "RED":
                    impact = NewsImpact.HIGH
                elif "MED" in impact_raw or impact_raw == "ORANGE" or impact_raw == "YELLOW":
                    impact = NewsImpact.MEDIUM
                elif "HOLIDAY" in impact_raw:
                    continue  # Skip holidays
                else:
                    impact = NewsImpact.LOW

                time_str = item.get("date", "")
                if not time_str:
                    continue

                try:
                    dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                    dt_utc = dt.astimezone(timezone.utc)
                except ValueError:
                    continue

                event_id = f"{currency}_{title}_{dt_utc.timestamp()}"

                event = NewsEvent(
                    event_id=event_id,
                    currency=currency,
                    title=title,
                    impact=impact,
                    event_time_utc=dt_utc,
                    forecast=item.get("forecast"),
                    previous=item.get("previous"),
                    actual=item.get("actual"),
                    source="ForexFactory"
                )
                events.append(event)
            except Exception as e:
                logger.debug(f"[NewsFilter] Error parsing news event item: {e}")
        return events

    def fetch_events(self) -> List[NewsEvent]:
        now = datetime.now(timezone.utc)
        
        # 1. Return memory-cached events if TTL is still valid
        if ForexFactoryNewsProvider._shared_cache_time is not None:
            elapsed = (now - ForexFactoryNewsProvider._shared_cache_time).total_seconds()
            if elapsed < ForexFactoryNewsProvider._cache_ttl_seconds and ForexFactoryNewsProvider._shared_cache_events:
                return ForexFactoryNewsProvider._shared_cache_events

        # 2. Try fetching live data from network
        raw_data = self._fetch_raw_json(self.PRIMARY_URL)
        if raw_data:
            events = self._parse_raw_items(raw_data)
            if events:
                ForexFactoryNewsProvider._shared_cache_events = events
                ForexFactoryNewsProvider._shared_cache_time = now
                self._save_disk_cache(raw_data)
                return events

        # 3. Memory cache fallback
        if ForexFactoryNewsProvider._shared_cache_events:
            logger.info("[NewsFilter] Using memory-cached calendar events.")
            return ForexFactoryNewsProvider._shared_cache_events

        # 4. Disk cache fallback
        disk_raw = self._load_disk_cache()
        if disk_raw:
            events = self._parse_raw_items(disk_raw)
            if events:
                logger.info(f"[NewsFilter] Loaded {len(events)} calendar events from disk cache ({self.DISK_CACHE_PATH}).")
                ForexFactoryNewsProvider._shared_cache_events = events
                ForexFactoryNewsProvider._shared_cache_time = now
                return events

        logger.warning("[NewsFilter] Failed to fetch news data and no disk cache available.")
        return []

    def _save_disk_cache(self, raw_data: List[Dict]):
        try:
            os.makedirs(os.path.dirname(self.DISK_CACHE_PATH), exist_ok=True)
            with open(self.DISK_CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(raw_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug(f"[NewsFilter] Could not save disk cache: {e}")

    def _load_disk_cache(self) -> Optional[List[Dict]]:
        try:
            if os.path.exists(self.DISK_CACHE_PATH):
                with open(self.DISK_CACHE_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.debug(f"[NewsFilter] Could not load disk cache: {e}")
        return None

    def _fetch_raw_json(self, url: str) -> Optional[List[Dict]]:
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            )
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as response:
                if response.status == 200:
                    content = response.read().decode("utf-8")
                    return json.loads(content)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                logger.warning(f"[NewsFilter] Rate limited (HTTP 429) when fetching {url}. Using cached/fallback data.")
            else:
                logger.warning(f"[NewsFilter] HTTP {e.code} error for {url}: {e.reason}")
        except Exception as e:
            logger.warning(f"[NewsFilter] Network error fetching {url}: {e}")
        return None


class FinancialModelingPrepProvider(BaseNewsProvider):
    """
    Financial Modeling Prep (FMP) Economic Calendar Provider implementation.
    """

    def __init__(self, api_key: str = "", timeout_seconds: int = 10):
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def fetch_events(self) -> List[NewsEvent]:
        if not self.api_key:
            return []
        url = f"https://financialmodelingprep.com/api/v3/economic_calendar?apikey={self.api_key}"
        events: List[NewsEvent] = []
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AlphaQuant/1.0"})
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    for item in data:
                        impact_str = str(item.get("impact", "")).upper()
                        impact = NewsImpact.HIGH if impact_str == "HIGH" else (NewsImpact.MEDIUM if impact_str == "MEDIUM" else NewsImpact.LOW)
                        dt_str = item.get("date", "")
                        if dt_str:
                            dt = datetime.fromisoformat(dt_str).replace(tzinfo=timezone.utc)
                            events.append(NewsEvent(
                                event_id=str(item.get("id", f"{item.get('currency')}_{item.get('event')}")),
                                currency=str(item.get("currency", "")).upper(),
                                title=str(item.get("event", "FMP News")),
                                impact=impact,
                                event_time_utc=dt,
                                forecast=str(item.get("estimate", "")),
                                previous=str(item.get("previous", "")),
                                actual=str(item.get("actual", "")),
                                source="FinancialModelingPrep"
                            ))
        except Exception as e:
            logger.warning(f"[NewsFilter] FMP news fetch error: {e}")
        return events


class NewsProviderFactory:
    @staticmethod
    def get_provider(provider_name: str = "forexfactory") -> BaseNewsProvider:
        name = provider_name.lower()
        if name == "fmp" or name == "financialmodelingprep":
            return FinancialModelingPrepProvider(api_key=settings.NEWS_API_KEY, timeout_seconds=settings.NEWS_TIMEOUT_SECONDS)
        return ForexFactoryNewsProvider(timeout_seconds=settings.NEWS_TIMEOUT_SECONDS)


class NewsFilter:
    """
    Institutional Grade Real-Time Economic News Filter.
    Features:
    - Thread-safe memory cache with automatic periodic refresh (15 mins)
    - Currency mapping (EURUSD -> EUR, USD; XAUUSD -> USD; GBPJPY -> GBP, JPY)
    - Rejects NEW trade entries during High-Impact news windows (e.g. ±30 minutes)
    - Graceful non-blocking fallback policies (FAIL_SAFE_NEWS)
    """

    def __init__(self, provider: Optional[BaseNewsProvider] = None):
        self.provider = provider or NewsProviderFactory.get_provider(settings.NEWS_PROVIDER)
        self._lock = threading.Lock()
        self._cached_events: List[NewsEvent] = []
        self._last_refresh: Optional[datetime] = None
        self._provider_failed: bool = False

    def refresh_events_if_needed(self, force: bool = False):
        now = datetime.now(timezone.utc)
        refresh_interval_sec = settings.NEWS_REFRESH_INTERVAL_MINUTES * 60

        with self._lock:
            if not force and self._last_refresh is not None:
                elapsed = (now - self._last_refresh).total_seconds()
                if elapsed < refresh_interval_sec:
                    return

        # Fetch outside lock to prevent blocking callers during HTTP request
        try:
            new_events = self.provider.fetch_events()
            with self._lock:
                if new_events:
                    self._cached_events = new_events
                    self._provider_failed = False
                elif not self._cached_events:
                    self._provider_failed = True
                self._last_refresh = datetime.now(timezone.utc)
        except Exception as e:
            logger.warning(f"[NewsFilter] Periodic event refresh error: {e}")
            with self._lock:
                self._provider_failed = True
                self._last_refresh = datetime.now(timezone.utc)

    @staticmethod
    def get_symbol_currencies(symbol: str) -> List[str]:
        # Strip broker suffixes (e.g. XAUUSDm, XAUUSD.c, EURUSD.)
        clean_symbol = symbol.upper().replace(".C", "").replace(".M", "").replace(".", "")
        if clean_symbol.endswith("M") and len(clean_symbol) > 6:
            clean_symbol = clean_symbol[:-1]

        # Commodity & Crypto Specific Mappings
        if clean_symbol.startswith("XAU") or clean_symbol.startswith("GOLD"):
            return ["USD"]
        if clean_symbol.startswith("XAG") or clean_symbol.startswith("SILVER"):
            return ["USD"]
        if clean_symbol.startswith("BTC") or clean_symbol.startswith("ETH"):
            return ["USD"]

        # Standard Forex Pairs (6 characters)
        if len(clean_symbol) >= 6:
            base = clean_symbol[:3]
            quote = clean_symbol[3:6]
            return [base, quote]

        return ["USD"]

    def is_news_blocked(
        self,
        symbol: str,
        minutes_before: Optional[int] = None,
        minutes_after: Optional[int] = None,
        current_time_utc: Optional[datetime] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Evaluates whether a symbol is blocked for NEW entry due to a HIGH impact economic event.
        Returns: Tuple[is_blocked, reason]
        """
        if not settings.NEWS_ENABLED:
            return False, None

        buf_before = minutes_before if minutes_before is not None else settings.NEWS_BLOCK_BEFORE_MINUTES
        buf_after = minutes_after if minutes_after is not None else settings.NEWS_BLOCK_AFTER_MINUTES
        now = current_time_utc or datetime.now(timezone.utc)

        self.refresh_events_if_needed()

        with self._lock:
            events_snapshot = list(self._cached_events)
            failed = self._provider_failed

        # Fail-Safe check if provider failed and cache is empty
        if failed and not events_snapshot:
            if settings.FAIL_SAFE_NEWS:
                reason = "Fail-Safe Active: Economic News Provider unavailable. Entry Vetoed."
                logger.warning(f"[NewsFilter] {reason}")
                return True, reason
            else:
                logger.warning(f"[NewsFilter] News provider unavailable. FAIL_SAFE_NEWS is False; proceeding without news filter.")
                return False, None

        currencies = self.get_symbol_currencies(symbol)

        for event in events_snapshot:
            if event.impact != NewsImpact.HIGH:
                continue

            if event.currency not in currencies:
                continue

            # Calculate window [event_time - minutes_before, event_time + minutes_after]
            window_start = event.event_time_utc - timedelta(minutes=buf_before)
            window_end = event.event_time_utc + timedelta(minutes=buf_after)

            if window_start <= now <= window_end:
                remaining_sec = (window_end - now).total_seconds()
                remaining_min = max(0, int(remaining_sec / 60))
                reason = (
                    f"High impact economic event '{event.title}' on {event.currency} at {event.event_time_utc.strftime('%H:%M UTC')}. "
                    f"Window active for next {remaining_min} mins."
                )
                logger.info(
                    f"Trade rejected due to economic news - symbol: {symbol}, event: '{event.title}', "
                    f"impact: {event.impact.value}, currency: {event.currency}, remaining_minutes: {remaining_min}"
                )
                return True, reason

        return False, None
