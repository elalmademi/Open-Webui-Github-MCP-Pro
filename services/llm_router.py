"""
LLM Router - Enrutamiento multi-proveedor con fallback, retry y métricas.
"""
import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from config.settings import get_settings
from services.catalog_service import CatalogService, ProviderInfo

logger = logging.getLogger(__name__)


@dataclass
class LLMMessage:
    role: str
    content: str


@dataclass
class LLMResponse:
    provider: str
    model: str
    content: str
    latency_ms: float
    success: bool
    error: Optional[str] = None


class LLMRouter:
    """
    Router LLM con:
    - Selección inteligente de proveedor (vía CatalogService)
    - Fallback automático en orden de prioridad
    - Retry con exponential backoff
    - Métricas de latencia y éxito por proveedor
    - Soporte streaming (opcional)
    """

    def __init__(
        self,
        catalog: CatalogService,
        settings=None,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.catalog = catalog
        self.settings = settings or get_settings()
        self._http_client = http_client
        self._own_client = http_client is None

    async def initialize(self) -> None:
        if self._own_client:
            self._http_client = httpx.AsyncClient(timeout=self.settings.llm_request_timeout)

    async def shutdown(self) -> None:
        if self._own_client and self._http_client:
            await self._http_client.aclose()

    def _build_candidates(
        self,
        criteria: str,
        preferred_provider: Optional[str] = None,
        preferred_model: Optional[str] = None,
    ) -> List[ProviderInfo]:
        """Construye lista de candidatos ordenados por prioridad."""
        candidates = []

        # 1. Proveedor preferido explícito
        if preferred_provider:
            provider = self.catalog.get_provider_info(preferred_provider)
            if provider and (provider.api_key or provider.no_key_required):
                candidates.append(provider)

        # 2. Mejor proveedor según criterio
        best = self.catalog.select_best_provider(criteria)
        if best and best not in candidates:
            candidates.append(best)

        # 3. Resto de proveedores configurados
        configured = self.catalog.get_configured_providers()
        for provider in configured.values():
            if provider not in candidates:
                candidates.append(provider)

        return candidates

    def _select_model(self, provider: ProviderInfo, preferred_model: Optional[str] = None) -> str:
        """Selecciona modelo del proveedor."""
        if preferred_model:
            # Verificar que el modelo existe en el proveedor
            for model in provider.models:
                if model.id == preferred_model:
                    return preferred_model
        # Default: primer modelo
        return provider.models[0].id if provider.models else "default"

    async def _call_provider(
        self,
        provider: ProviderInfo,
        model: str,
        messages: List[LLMMessage],
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        """Llama a un proveedor específico."""
        base_url = provider.baseUrl.rstrip("/")
        api_key = provider.api_key

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        start = time.perf_counter()
        try:
            resp = await self._http_client.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            latency = (time.perf_counter() - start) * 1000

            if resp.status_code == 401:
                return LLMResponse(
                    provider=provider.name,
                    model=model,
                    content="",
                    latency_ms=latency,
                    success=False,
                    error="API Key inválida",
                )
            if resp.status_code == 429:
                return LLMResponse(
                    provider=provider.name,
                    model=model,
                    content="",
                    latency_ms=latency,
                    success=False,
                    error="Rate limit",
                )

            resp.raise_for_status()
            data = resp.json()

            # Extraer contenido (compatible OpenAI + reasoning)
            content = self._extract_content(data, provider.name)

            return LLMResponse(
                provider=provider.name,
                model=model,
                content=content,
                latency_ms=latency,
                success=True,
            )

        except httpx.TimeoutException:
            return LLMResponse(
                provider=provider.name,
                model=model,
                content="",
                latency_ms=(time.perf_counter() - start) * 1000,
                success=False,
                error="Timeout",
            )
        except httpx.HTTPStatusError as e:
            return LLMResponse(
                provider=provider.name,
                model=model,
                content="",
                latency_ms=(time.perf_counter() - start) * 1000,
                success=False,
                error=f"HTTP {e.response.status_code}: {e.response.text[:200]}",
            )
        except Exception as e:
            return LLMResponse(
                provider=provider.name,
                model=model,
                content="",
                latency_ms=(time.perf_counter() - start) * 1000,
                success=False,
                error=str(e),
            )

    def _extract_content(self, data: Dict, provider_name: str) -> str:
        """Extrae contenido de respuesta (maneja content, reasoning, reasoning_content)."""
        choices = data.get("choices", [])
        if not choices:
            return ""

        message = choices[0].get("message", {})
        content = message.get("content", "")

        if content and content.strip():
            return content.strip()

        # Fallback a reasoning fields
        for field in ["reasoning", "reasoning_content"]:
            reasoning = message.get(field, "")
            if reasoning and reasoning.strip():
                logger.info(f"{provider_name}: content vacío, usando {field} ({len(reasoning)} chars)")
                return reasoning.strip()

        return ""

    async def chat(
        self,
        prompt: str,
        criteria: str = "balanced",
        system_prompt: Optional[str] = None,
        preferred_provider: Optional[str] = None,
        preferred_model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> LLMResponse:
        """
        Chat con fallback automático.
        Args:
            prompt: Mensaje del usuario
            criteria: Criterio selección ('speed', 'code', 'context', 'fallback', 'privacy', 'balanced')
            system_prompt: System prompt opcional
            preferred_provider: Forzar proveedor específico
            preferred_model: Forzar modelo específico
            temperature: Temperatura sampling
            max_tokens: Max tokens respuesta
        Returns:
            LLMResponse con contenido o error
        """
        candidates = self._build_candidates(criteria, preferred_provider, preferred_model)

        if not candidates:
            return LLMResponse(
                provider="none",
                model="none",
                content="",
                latency_ms=0,
                success=False,
                error="No hay proveedores configurados con API key",
            )

        messages = []
        if system_prompt:
            messages.append(LLMMessage(role="system", content=system_prompt))
        messages.append(LLMMessage(role="user", content=prompt))

        last_error = None
        for provider in candidates:
            model = self._select_model(provider, preferred_model)
            logger.info(f"Intentando LLM: {provider.name} / {model} (criteria: {criteria})")

            response = await self._call_provider(
                provider, model, messages, temperature, max_tokens
            )

            # Registrar métrica
            self.catalog.record_request(provider.name, response.success, response.latency_ms)

            if response.success:
                logger.info(f"✅ Respuesta exitosa de {provider.name} ({response.latency_ms:.0f}ms)")
                return response
            else:
                last_error = response.error
                logger.warning(f"❌ {provider.name} falló: {last_error}. Probando siguiente...")

        return LLMResponse(
            provider="none",
            model="none",
            content="",
            latency_ms=0,
            success=False,
            error=f"Todos los proveedores fallaron. Último error: {last_error}",
        )

    async def chat_with_retry(
        self,
        prompt: str,
        criteria: str = "balanced",
        system_prompt: Optional[str] = None,
        max_retries: int = 3,
        **kwargs,
    ) -> LLMResponse:
        """Chat con retry a nivel de router (reintenta toda la cadena de fallback)."""
        for attempt in range(max_retries):
            response = await self.chat(prompt, criteria, system_prompt, **kwargs)
            if response.success:
                return response
            if attempt < max_retries - 1:
                wait = self.settings.llm_base_backoff * (attempt + 1)
                logger.warning(f"Router fallback falló, reintentando en {wait}s (intento {attempt + 1}/{max_retries})")
                await asyncio.sleep(wait)
        return response