"""
Structured Logging Middleware - JSON logs con request ID, tracing, métricas.
Compatible con Loki, Datadog, Elasticsearch, etc.
"""
import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from typing import Any, Callable, Dict, Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# Context variable para request ID
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    """Filtro que inyecta request_id en todos los log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JSONFormatter(logging.Formatter):
    """Formatter JSON estructurado para logs."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }

        # Añadir campos extra si existen
        extra_fields = {
            "method": getattr(record, "method", None),
            "path": getattr(record, "path", None),
            "status_code": getattr(record, "status_code", None),
            "duration_ms": getattr(record, "duration_ms", None),
            "client_ip": getattr(record, "client_ip", None),
            "user_agent": getattr(record, "user_agent", None),
            "error": getattr(record, "error", None),
        }
        log_obj.update({k: v for k, v in extra_fields.items() if v is not None})

        # Exception info
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_obj, ensure_ascii=False)


class LoggingMiddleware(BaseHTTPMiddleware):
    """Middleware que loguea requests/responses con structured logging."""

    def __init__(self, app, logger_name: str = "mcp.access"):
        super().__init__(app)
        self.logger = logging.getLogger(logger_name)
        self.logger.addFilter(RequestIdFilter())

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Generar/obtener request ID
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
        request_id_var.set(request_id)

        # Request headers para response
        request.headers.__dict__["_list"].append(("x-request-id", request_id))

        start = time.perf_counter()
        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "-")

        # Log request
        self.logger.info(
            "Request started",
            extra={
                "method": request.method,
                "path": request.url.path,
                "client_ip": client_ip,
                "user_agent": user_agent,
            },
        )

        try:
            response = await call_next(request)
            duration_ms = (time.perf_counter() - start) * 1000

            # Log response
            self.logger.info(
                "Request completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round(duration_ms, 2),
                    "client_ip": client_ip,
                },
            )

            # Añadir headers de tracing
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Response-Time-MS"] = str(round(duration_ms, 2))

            return response

        except Exception as e:
            duration_ms = (time.perf_counter() - start) * 1000
            self.logger.error(
                "Request failed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round(duration_ms, 2),
                    "client_ip": client_ip,
                    "error": str(e),
                },
                exc_info=True,
            )
            raise


def setup_structured_logging(
    level: str = "INFO",
    format: str = "json",  # "json" | "text"
    loggers: Optional[Dict[str, str]] = None,
) -> None:
    """
    Configura logging estructurado global.
    Debe llamarse al inicio de la aplicación (en main.py lifespan).
    """
    # Limpiar handlers existentes
    root_logger = logging.getLogger()
    root_logger.handlers.clear()

    # Configurar nivel
    log_level = getattr(logging, level.upper(), logging.INFO)
    root_logger.setLevel(log_level)

    # Handler consola
    handler = logging.StreamHandler(sys.stdout)

    if format.lower() == "json":
        formatter = JSONFormatter(datefmt="%Y-%m-%dT%H:%M:%S")
    else:
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s [%(request_id)s]: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    handler.setFormatter(formatter)
    handler.addFilter(RequestIdFilter())
    root_logger.addHandler(handler)

    # Configurar loggers específicos
    default_loggers = {
        "uvicorn": "WARNING",
        "uvicorn.access": "WARNING",
        "httpx": "WARNING",
        "httpcore": "WARNING",
        "github": "INFO",
        "mcp": "INFO",
    }

    if loggers:
        default_loggers.update(loggers)

    for name, lvl in default_loggers.items():
        logging.getLogger(name).setLevel(getattr(logging, lvl.upper(), logging.INFO))

    # Capturar warnings
    logging.captureWarnings(True)

    # Log inicial
    logging.getLogger("mcp.startup").info(
        "Structured logging initialized",
        extra={"format": format, "level": level},
    )


def get_logger(name: str) -> logging.Logger:
    """Obtiene logger con configuración heredada."""
    return logging.getLogger(name)