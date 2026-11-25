"""Adaptador ExternalLLMService - Wrapper sobre LLMRouter + CatalogService"""
import asyncio
from typing import Optional
from config.settings import Settings
from services.catalog_service import CatalogService
from services.llm_router import LLMRouter

class ExternalLLMService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._catalog: Optional[CatalogService] = None
        self._router: Optional[LLMRouter] = None
        self._initialized = False

    async def _ensure_initialized(self):
        if self._initialized:
            return
        self._catalog = CatalogService(self.settings)
        await self._catalog.initialize()
        self._router = LLMRouter(self._catalog, self.settings)
        await self._router.initialize()
        self._initialized = True

    async def find_free_model(self, criterio: str = "equilibrado") -> str:
        await self._ensure_initialized()
        provider = self._catalog.select_best_provider(criterio)
        if not provider:
            return "No hay proveedores configurados con API key"
        best_model = provider.models[0] if provider.models else None
        model_id = best_model.id if best_model else "N/A"
        modality = best_model.modality if best_model else "text"
        context = best_model.context if best_model else "N/A"
        return (
            f"Proveedor recomendado: {provider.name}\n"
            f"Modelo: {model_id}\n"
            f"Categoría: {provider.category}\n"
            f"Modalidad: {modality}\n"
            f"Contexto: {context}\n"
            f"Requiere API key: {not provider.no_key_required}\n"
            f"API key configurada: {bool(provider.api_key)}"
        )

    async def query(self, prompt: str, model: str = "", temperatura: float = 0.7) -> str:
        await self._ensure_initialized()
        response = await self._router.chat_with_retry(
            prompt=prompt,
            criteria="balanced",
            preferred_model=model if model else None,
            temperature=temperatura,
            max_tokens=2000,
        )
        if response.success:
            return response.content
        else:
            return f"Error consultando LLM: {response.error}"

    async def shutdown(self):
        if self._router:
            await self._router.shutdown()
        if self._catalog:
            await self._catalog.shutdown()
