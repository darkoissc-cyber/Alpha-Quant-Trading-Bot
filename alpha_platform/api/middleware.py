"""
API Middleware: rate limiting, security headers, request size limits.
Lightweight implementation that does not require Redis/external deps.
"""
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from alpha_platform.config.logging_config import logger


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Simple sliding-window rate limiter. Defaults:
      - 60 requests/minute per client IP for normal endpoints
      - 5 requests/minute per client IP for sensitive endpoints
        (kill switch, trade test, stress test)
    """

    NORMAL_LIMIT = 60
    SENSITIVE_LIMIT = 5
    WINDOW_SECONDS = 60.0

    SENSITIVE_PATHS = (
        "/api/risk/trigger-kill-switch",
        "/api/trade/test",
        "/api/stress-test/run",
    )

    def __init__(self, app):
        super().__init__(app)
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)

    def _is_sensitive(self, path: str) -> bool:
        return any(path.startswith(p) for p in self.SENSITIVE_PATHS)

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        # Don't rate-limit health/metrics endpoints (dashboard polls these)
        if request.url.path in ("/", "/api/system/health", "/api/system/metrics", "/ws"):
            return await call_next(request)

        now = time.time()
        bucket = self._hits[client_ip]
        # Prune old entries
        while bucket and now - bucket[0] > self.WINDOW_SECONDS:
            bucket.popleft()

        limit = self.SENSITIVE_LIMIT if self._is_sensitive(request.url.path) else self.NORMAL_LIMIT
        if len(bucket) >= limit:
            logger.warning(
                f"[RateLimit] Blocking {client_ip} on {request.url.path} "
                f"({len(bucket)} hits in {self.WINDOW_SECONDS}s window, limit={limit})"
            )
            return JSONResponse(
                status_code=429,
                content={
                    "error": "RATE_LIMITED",
                    "message": f"Too many requests. Limit: {limit}/{int(self.WINDOW_SECONDS)}s",
                    "retry_after_seconds": int(self.WINDOW_SECONDS),
                },
                headers={"Retry-After": str(int(self.WINDOW_SECONDS))},
            )

        bucket.append(now)
        response: Response = await call_next(request)

        # Add basic security headers to every response
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-XSS-Protection", "1; mode=block")
        return response
