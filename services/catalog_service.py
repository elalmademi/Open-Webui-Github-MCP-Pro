"""
Catalog Service - Gestión de catálogo de proveedores LLM.
Carga desde repo local (awesome-free-llm-apis), cachea en Redis, enriquece con metadata.
"""
import asyncio
import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import redis.asyncio as redis
import yaml

from config.settings import get_settings

logger = logging.getLogger(__name__)

# ─── Mapeo Proveedor → Variable de Entorno ───
PROVIDER_ENV_MAP = {
    "Aion Labs": "AIONLABS_API_KEY",
    "Cohere": "COHERE_API_KEY",
    "Google Gemini": "GEMINI_API_KEY",
    "Mistral AI": "MISTRAL_API_KEY",
    "Z AI (Zhipu AI)": "ZAI_API_KEY",
    "Cloudflare Workers AI": "CLOUDFLARE_API_KEY",
    "Groq": "GROQ_API_KEY",
    "Kilo Code": "KILO_API_KEY",
    "LLM7.io": "LLM7_API_KEY",
    "ModelScope": "MODELSCOPE_API_KEY",
    "NVIDIA NIM": "NVIDIA_API_KEY",
    "Ollama Cloud": "OLLAMA_API_KEY",
    "OpenRouter": "OPENROUTER_API_KEY",
    "OVHcloud AI Endpoints": "OVH_API_KEY",
    "SiliconFlow": "SILICONFLOW_API_KEY",
    "ModelScope": "MODELSCOPE_API_KEY",
    "Aion Labs": "AIONLABS_API_KEY",
}

# ─── Data Classes ───

@dataclass(frozen=True)
class ProviderModel:
    id: str
    modality: str = "text"
    context: str = "8K"


@dataclass
class ProviderInfo:
    name: str
    baseUrl: str
    models: List[ProviderModel]
    category: str = "general"
    api_key: Optional[str] = None
    env_var: Optional[str] = None
    no_key_required: bool = False
    _enriched: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "baseUrl": self.baseUrl,
            "models": [{"id": m.id, "modality": m.modality, "context": m.context} for m in self.models],
            "category": self.category,
            "api_key": self.api_key,
            "env_var": self.env_var,
            "no_key_required": self.no_key_required,
            "_enriched": self._enriched,
        }


@dataclass
class ProviderMetrics:
    success: int = 0
    errors: int = 0
    total_latency: float = 0.0

    @property
    def error_rate(self) -> float:
        total = self.success + self.errors
        return self.errors / total if total > 0 else 0.0

    @property
    def avg_latency(self) -> float:
        return self.total_latency / self.success if self.success > 0 else 0.0


# ─── Service ───

class CatalogService:
    """
    Catálogo de proveedores LLM con:
    - Carga desde repo Git local (data.json + README metadata)
    - Cache en Redis con TTL configurable
    - Enriquecimiento con providers.yaml (env vars, tags, best_for)
    - Selección inteligente por criterio (speed, code, context, etc.)
    - Métricas de salud por proveedor
    """

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self._redis: Optional[redis.Redis] = None
        self._providers_cache: Optional[Dict[str, ProviderInfo]] = None
        self._last_cache_time: float = 0
        self._cache_lock = asyncio.Lock()
        self._metrics: Dict[str, ProviderMetrics] = {}
        self._configured_providers: Dict[str, Dict] = {}
        self._local_repo_path = self.settings.providers_local_path
        self._repo_url = self.settings.providers_repo_url

    async def initialize(self) -> None:
        """Inicializa conexión Redis y valida claves API."""
        self._redis = redis.Redis(
            host=self.settings.redis_host,
            port=self.settings.redis_port,
            db=self.settings.redis_db,
            password=self.settings.redis_password,
            decode_responses=True,
        )
        try:
            await self._redis.ping()
            logger.info("Redis conectado para catálogo")
        except Exception as e:
            logger.warning(f"Redis no disponible, usando cache en memoria: {e}")
            self._redis = None

        await self._validate_api_keys()

    async def shutdown(self) -> None:
        if self._redis:
            await self._redis.close()

    # ─── Repo Sync ───

    async def _sync_repo(self) -> None:
        """Clona o actualiza repo awesome-free-llm-apis (ejecutado en thread pool)."""
        loop = asyncio.get_event_loop()

        def _do_sync() -> None:
            if self._local_repo_path.exists():
                logger.info("Actualizando repo awesome-free-llm-apis...")
                result = subprocess.run(
                    ["git", "-C", str(self._local_repo_path), "pull", "--ff-only"],
                    capture_output=True, text=True, timeout=60
                )
                if result.returncode != 0:
                    logger.warning(f"git pull falló: {result.stderr}. Reclonando...")
                    subprocess.run(["rm", "-rf", str(self._local_repo_path)], check=True)
                    self._clone_repo()
                else:
                    logger.info("Repo actualizado")
            else:
                self._clone_repo()

        def _clone_repo() -> None:
            logger.info("Clonando awesome-free-llm-apis...")
            result = subprocess.run(
                ["git", "clone", "--depth", "1", self._repo_url, str(self._local_repo_path)],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode != 0:
                raise RuntimeError(f"Failed to clone repo: {result.stderr}")
            logger.info("Repo clonado")

        await loop.run_in_executor(None, _do_sync)

    # ─── Parse & Load ───

    def _parse_readme_metadata(self, readme_path: Path) -> Dict[str, Dict]:
        """Extrae metadata de la tabla del README (provider → description, tags, best_for)."""
        metadata = {}
        try:
            content = readme_path.read_text(encoding="utf-8")
            import re
            table_pattern = r"\|(?:\s*[^|]+\s*\|){3,}"
            tables = re.findall(table_pattern, content, re.MULTILINE)
            for table in tables:
                rows = [row.strip() for row in table.strip().split("\n") if row.strip()]
                if len(rows) < 3:
                    continue
                headers = [h.strip().lower() for h in rows[0].split("|") if h.strip()]
                provider_idx = next((i for i, h in enumerate(headers) if "provider" in h or "name" in h), 0)
                desc_idx = next((i for i, h in enumerate(headers) if "descript" in h or "detail" in h), 1)
                tags_idx = next((i for i, h in enumerate(headers) if "tag" in h), -1)
                best_for_idx = next((i for i, h in enumerate(headers) if "best" in h), -1)
                status_idx = next((i for i, h in enumerate(headers) if "status" in h), -1)

                for row in rows[2:]:
                    cols = [c.strip() for c in row.split("|") if c.strip()]
                    if len(cols) <= max(provider_idx, desc_idx):
                        continue
                    provider_name = re.sub(r"[`*\[\]#]", "", cols[provider_idx]).strip()
                    if not provider_name:
                        continue
                    enriched = {"source": "readme"}
                    if desc_idx < len(cols):
                        enriched["description"] = re.sub(r"[`*\[\]#]", "", cols[desc_idx]).strip()
                    if tags_idx >= 0 and tags_idx < len(cols):
                        tags = [t.strip() for t in cols[tags_idx].split(",") if t.strip()]
                        enriched["tags"] = tags
                    if best_for_idx >= 0 and best_for_idx < len(cols):
                        best = [b.strip() for b in cols[best_for_idx].split(",") if b.strip()]
                        enriched["best_for"] = best
                    if status_idx >= 0 and status_idx < len(cols):
                        enriched["status"] = cols[status_idx].strip()
                    metadata[provider_name] = enriched
        except Exception as e:
            logger.warning(f"No se pudo parsear README para metadata: {e}")
        return metadata

    async def _load_providers_from_repo(self) -> Dict[str, ProviderInfo]:
        """Carga proveedores desde data.json local + enriquece con README + providers.yaml."""
        await self._sync_repo()

        data_json = self._local_repo_path / "data.json"
        if not data_json.exists():
            raise FileNotFoundError(f"No existe {data_json} tras sync_repo()")

        raw_data = json.loads(data_json.read_text(encoding="utf-8"))

        providers_yaml_path = Path(__file__).parent.parent / "config" / "providers.yaml"
        yaml_config = {}
        if providers_yaml_path.exists():
            yaml_config = yaml.safe_load(providers_yaml_path.read_text(encoding="utf-8")) or {}
            yaml_config = yaml_config.get("providers", {})

        readme_path = self._local_repo_path / "README.md"
        readme_meta = {}
        if readme_path.exists():
            readme_meta = self._parse_readme_metadata(readme_path)

        providers = {}
        for provider_data in raw_data.get("providers", []):
            name = provider_data.get("name")
            if not name:
                continue

            models = [
                ProviderModel(
                    id=m.get("id", ""),
                    modality=m.get("modality", "text"),
                    context=m.get("context", "8K"),
                )
                for m in provider_data.get("models", [])
            ]

            yaml_info = yaml_config.get(name, {})

            env_var = yaml_info.get("env_var") or f"{name.upper().replace(' ', '_').replace('.', '_').replace('-', '_')}_API_KEY"
            api_key = os.getenv(env_var) if env_var else None
            no_key_required = yaml_info.get("no_key_required", False) or name in ["Kilo Code", "LLM7.io", "OVHcloud AI Endpoints"]

            enriched = provider_data.get("_enriched", {})
            if name in readme_meta:
                enriched.update(readme_meta[name])
            if "tags" in yaml_info:
                enriched["tags"] = yaml_info["tags"]
            if "best_for" in yaml_info:
                enriched["best_for"] = yaml_info["best_for"]
            if "status" in yaml_info:
                enriched["status"] = yaml_info["status"]

            provider = ProviderInfo(
                name=name,
                baseUrl=provider_data.get("baseUrl", ""),
                models=models,
                category=yaml_info.get("category", provider_data.get("category", "general")),
                api_key=api_key,
                env_var=env_var if env_var else None,
                no_key_required=no_key_required,
                _enriched=enriched,
            )
            providers[name] = provider
            self._metrics[name] = ProviderMetrics()

        logger.info(f"Catálogo cargado: {len(providers)} proveedores, {sum(1 for p in providers.values() if p.api_key or p.no_key_required)} configurados")
        return providers

    # ─── Cache Management ───

    async def get_providers(self, force_refresh: bool = False) -> Dict[str, ProviderInfo]:
        """Obtiene proveedores con cache (Redis + memoria)."""
        async with self._cache_lock:
            current_time = time.time()
            cache_valid = (
                not force_refresh
                and self._providers_cache is not None
                and (current_time - self._last_cache_time) < self.settings.cache_ttl
            )

            if cache_valid:
                return self._providers_cache

            if self._redis:
                try:
                    cached = await self._redis.get("catalog:providers")
                    if cached and not force_refresh:
                        data = json.loads(cached)
                        self._providers_cache = {k: ProviderInfo(**v) for k, v in data.items()}
                        self._last_cache_time = current_time
                        logger.debug("Catálogo cargado desde Redis")
                        return self._providers_cache
                except Exception as e:
                    logger.warning(f"Error leyendo cache Redis: {e}")

            logger.info("Cargando catálogo desde repo local...")
            self._providers_cache = await self._load_providers_from_repo()
            self._last_cache_time = current_time

            if self._redis:
                try:
                    data = {k: v.to_dict() for k, v in self._providers_cache.items()}
                    await self._redis.setex("catalog:providers", self.settings.cache_ttl, json.dumps(data))
                except Exception as e:
                    logger.warning(f"Error guardando cache Redis: {e}")

            return self._providers_cache

    def get_configured_providers(self) -> Dict[str, ProviderInfo]:
        """Retorna solo proveedores con API key configurada o no_key_required."""
        if not self._providers_cache:
            return {}
        return {
            k: v for k, v in self._providers_cache.items()
            if v.api_key or v.no_key_required
        }

    # ─── Provider Selection ───

    def select_best_provider(self, criteria: str) -> Optional[ProviderInfo]:
        """Selecciona mejor proveedor según criterio: 'speed', 'code', 'context', 'fallback', 'privacy', etc."""
        configured = self.get_configured_providers()
        if not configured:
            return None

        criteria_lower = criteria.lower()
        scored = []

        for name, info in configured.items():
            metrics = self._metrics.get(name, ProviderMetrics())
            if metrics.error_rate > 0.5:
                continue

            score = 0
            for model in info.models:
                modality = model.modality.lower()
                context_str = model.context.replace("K", "000").replace("M", "000000")
                try:
                    context = int(''.join(filter(str.isdigit, context_str)))
                except:
                    context = 0

                if any(x in criteria_lower for x in ["código", "code", "program", "coding"]):
                    if "code" in modality:
                        score += 15
                    if name in ["Groq", "Cerebras", "Kilo Code", "Mistral AI"]:
                        score += 10

                if any(x in criteria_lower for x in ["contexto", "context", "largo", "long"]):
                    score += min(context // 10000, 50)

                if any(x in criteria_lower for x in ["rápid", "fast", "speed", "velocidad"]):
                    if name in ["Groq", "Cerebras", "Kilo Code"]:
                        score += 25

                if any(x in criteria_lower for x in ["privado", "privacy", "local", "offline"]):
                    if info.no_key_required or "local" in info.category:
                        score += 30

                if "fallback" in criteria_lower:
                    if name == "OpenRouter":
                        score += 20

                tags = info._enriched.get("tags", []) if isinstance(info._enriched.get("tags"), list) else []
                best_for = info._enriched.get("best_for", []) if isinstance(info._enriched.get("best_for"), list) else []

                if "speed" in criteria_lower and "speed" in tags:
                    score += 20
                if "code" in criteria_lower and "code" in best_for:
                    score += 15
                if "fallback" in criteria_lower and "fallback" in tags:
                    score += 10
                if "privado" in criteria_lower and info._enriched.get("status") == "local":
                    score += 25

            if score > 0:
                scored.append((score, name, info))

        if not scored:
            name = next(iter(configured))
            return configured[name]

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][2]

    # ─── Metrics ───

    def record_request(self, provider: str, success: bool, latency_ms: float) -> None:
        if provider not in self._metrics:
            self._metrics[provider] = ProviderMetrics()
        m = self._metrics[provider]
        if success:
            m.success += 1
            m.total_latency += latency_ms
        else:
            m.errors += 1

    def get_metrics(self) -> Dict[str, Dict]:
        return {
            name: {
                "success": m.success,
                "errors": m.errors,
                "error_rate": m.error_rate,
                "avg_latency_ms": m.avg_latency,
            }
            for name, m in self._metrics.items()
        }

    def get_provider_info(self, name: str) -> Optional[ProviderInfo]:
        if not self._providers_cache:
            return None
        return self._providers_cache.get(name)

    # ─── NUEVO: Método faltante que causaba el error ───

    async def _validate_api_keys(self) -> None:
        """Valida qué proveedores tienen API keys configuradas y los marca como disponibles."""
        self._configured_providers = {}
        self._provider_metrics = {}

        try:
            data = await self.get_providers()
        except Exception as e:
            logger.warning(f"No se pudo cargar catálogo de proveedores: {e}")
            return

        for provider in data.get("providers", []):
            name = provider.get("name")
            if not name:
                continue

            env_var = PROVIDER_ENV_MAP.get(name)
            api_key = os.getenv(env_var) if env_var else None
            no_key_required = provider.get("no_key_required", False) or name in [
                "Kilo Code", "LLM7.io", "OVHcloud AI Endpoints"
            ]

            if api_key or no_key_required:
                enriched = provider.get("_enriched", {})
                self._configured_providers[name] = {
                    "baseUrl": provider.get("baseUrl", ""),
                    "api_key": api_key,
                    "models": provider.get("models", []),
                    "category": provider.get("category", "general"),
                    "no_key_required": no_key_required,
                    "env_var": env_var,
                    "_enriched": enriched,
                }
                self._provider_metrics[name] = ProviderMetrics()
                logger.info(f"Proveedor configurado: {name}")