"""
Configuración tipada con Pydantic Settings.
Centraliza todas las variables de entorno con validación y defaults.
"""
from functools import lru_cache
from pathlib import Path
from typing import Optional, List
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración global de la aplicación."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ─── App ───
    app_name: str = "GitHub MCP Server Pro"
    app_version: str = "2.6.0"
    debug: bool = Field(default=False, description="Modo debug")
    environment: str = Field(default="production", description="Entorno: development|staging|production")

    # ─── Server ───
    host: str = Field(default="0.0.0.0", description="Host del servidor")
    port: int = Field(default=8888, description="Puerto del servidor")
    workers: int = Field(default=1, description="Workers Uvicorn")

    # ─── GitHub ───
    github_token: Optional[str] = Field(default=None, description="GitHub Personal Access Token")
    github_timeout: int = Field(default=30, description="Timeout GitHub API (segundos)")
    github_max_retries: int = Field(default=3, description="Reintentos GitHub API")

    # ─── Open WebUI ───
    openwebui_url: str = Field(default="http://open-webui-dev:8080", description="URL Open WebUI")

    # ─── Cache & Redis ───
    redis_host: str = Field(default="redis", description="Host Redis")
    redis_port: int = Field(default=6379, description="Puerto Redis")
    redis_db: int = Field(default=0, description="DB Redis")
    redis_password: Optional[str] = Field(default=None, description="Password Redis")
    cache_ttl: int = Field(default=86400, description="TTL cache catálogo (segundos)")

    # ─── Local FS ───
    local_docs_path: Path = Field(default=Path("/app/local_docs"), description="Ruta documentos locales (RO)")
    workspace_path: Path = Field(default=Path("/app/workspace"), description="Ruta workspace (RW)")

    # ─── Providers Catalog ───
    providers_repo_url: str = Field(
        default="https://github.com/mnfst/awesome-free-llm-apis.git",
        description="Repo catálogo proveedores"
    )
    providers_local_path: Path = Field(
        default=Path("/app/awesome-free-llm-apis"),
        description="Path local repo catálogo"
    )

    # ─── LLM Router ───
    llm_request_timeout: float = Field(default=30.0, description="Timeout requests LLM (segundos)")
    llm_max_retries: int = Field(default=3, description="Reintentos LLM")
    llm_base_backoff: float = Field(default=1.5, description="Backoff base LLM")

    # ─── Mobile Testing ───
    appium_host: str = Field(default="appium", description="Host Appium server")
    appium_port: int = Field(default=4723, description="Puerto Appium server")
    device_reservation_ttl: int = Field(default=1800, description="TTL reserva dispositivo (segundos)")
    max_device_reservation_minutes: int = Field(default=120, description="Máx minutos reserva dispositivo")

    # ─── Security ───
    api_keys: List[str] = Field(default_factory=list, description="API Keys válidas (vacío = sin auth)")
    cors_origins: List[str] = Field(default_factory=lambda: ["*"], description="Orígenes CORS permitidos")
    rate_limit_requests: int = Field(default=100, description="Requests por ventana rate limit")
    rate_limit_window: int = Field(default=60, description="Ventana rate limit (segundos)")

    # ─── Observability ───
    log_level: str = Field(default="INFO", description="Nivel logging")
    log_format: str = Field(default="json", description="Formato logs: json|text")
    enable_metrics: bool = Field(default=True, description="Habilitar métricas Prometheus")
    metrics_port: int = Field(default=9090, description="Puerto métricas")

    @field_validator("local_docs_path", "workspace_path", "providers_local_path", mode="before")
    @classmethod
    def _ensure_path(cls, v):
        if isinstance(v, str):
            return Path(v)
        return v

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",")]
        return v

    @field_validator("api_keys", mode="before")
    @classmethod
    def _parse_api_keys(cls, v):
        if isinstance(v, str):
            return [k.strip() for k in v.split(",") if k.strip()]
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton de settings (cacheado)."""
    return Settings()


# Instancia global para importación fácil
settings = get_settings()