"""
Rate Limiting Middleware - Protege endpoints MCP de abuso.
Usa SlowAPI (compatible con FastAPI/Starlette).
"""
import time
from typing import Callable, Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from config.settings import get_settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiter simple en memoria (para producción usar Redis).
    Límite por IP + User-Agent.
    """

    def __init__(self, app, requests_per_window: int = 100, window_seconds: int = 60):
        super().__init__(app)
        self.requests_per_window = requests_per_window
        self.window_seconds = window_seconds
        self._requests: dict = {}  # key -> [(timestamp, count)]

    def _get_client_key(self, request: Request) -> str:
        """Genera clave única por cliente."""
        ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "")[:50]
        return f"{ip}:{user_agent}"

    def _cleanup_old(self, key: str, now: float) -> None:
        """Elimina entradas fuera de la ventana."""
        if key in self._requests:
            self._requests[key] = [
                (ts, cnt) for ts, cnt in self._requests[key]
                if now - ts < self.window_seconds
            ]

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Solo limitar endpoints de tools (/tools/*) y health
        path = request.url.path
        if not (path.startswith("/tools/") or path == "/health"):
            return await call_next(request)

        key = self._get_client_key(request)
        now = time.time()

        self._cleanup_old(key, now)

        current_count = sum(cnt for _, cnt in self._requests.get(key, []))

        if current_count >= self.requests_per_window:
            # Rate limit exceeded
            retry_after = self.window_seconds
            if self._requests.get(key):
                oldest = min(ts for ts, _ in self._requests[key])
                retry_after = int(oldest + self.window_seconds - now) + 1

            return JSONResponse(
                status_code=429,
                content={
                    "error": "Rate limit exceeded",
                    "message": f"Máximo {self.requests_per_window} requests por {self.window_seconds}s",
                    "retry_after": retry_after,
                },
                headers={
                    "X-RateLimit-Limit": str(self.requests_per_window),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(now + retry_after)),
                    "Retry-After": str(retry_after),
                },
            )

        # Incrementar contador
        if key not in self._requests:
            self._requests[key] = []
        self._requests[key].append((now, 1))

        # Procesar request
        response = await call_next(request)

        # Headers de rate limit
        remaining = max(0, self.requests_per_window - current_count - 1)
        response.headers["X-RateLimit-Limit"] = str(self.requests_per_window)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(int(now + self.window_seconds))

        return response


def create_rate_limiter(requests_per_window: Optional[int] = None, window_seconds: Optional[int] = None):
    """Factory para crear middleware con settings."""
    settings = get_settings()
    rpw = requests_per_window or settings.rate_limit_requests
    ws = window_seconds or settings.rate_limit_window
    return lambda app: RateLimitMiddleware(app, rpw, ws)