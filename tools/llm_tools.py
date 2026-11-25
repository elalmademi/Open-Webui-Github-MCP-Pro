"""
LLM Tools MCP - Tools para consulta multi-proveedor con routing inteligente.
"""
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from services.catalog_service import CatalogService
from services.llm_router import LLMRouter, LLMResponse


def register_llm_tools(mcp: FastMCP, catalog: CatalogService, llm_router: LLMRouter):
    """Registra tools de LLM routing y catálogo."""

    @mcp.tool()
    async def buscar_modelo_gratis(criterio: str) -> Dict[str, Any]:
        """
        Busca el mejor modelo gratuito según criterio.
        
        Args:
            criterio: Descripción de necesidad (ej: "modelo rápido para código", 
                      "contexto largo para documentos", "modelo local privado", 
                      "fallback general", "razonamiento complejo")
        Returns:
            Dict con proveedor recomendado, modelo, y razones
        """
        provider = catalog.select_best_provider(criterio)
        if not provider:
            return {"error": "No hay proveedores configurados con API key"}

        best_model = provider.models[0] if provider.models else None
        return {
            "proveedor": provider.name,
            "modelo_recomendado": best_model.id if best_model else "N/A",
            "categoria": provider.category,
            "modalidad": best_model.modality if best_model else "text",
            "contexto": best_model.context if best_model else "N/A",
            "requiere_api_key": not provider.no_key_required,
            "api_key_configurada": bool(provider.api_key),
            "tags": provider._enriched.get("tags", []),
            "best_for": provider._enriched.get("best_for", []),
            "descripcion": provider._enriched.get("description", ""),
        }

    @mcp.tool()
    async def consultar_llm_externo(
        prompt: str,
        criterio: str = "balanced",
        system_prompt: Optional[str] = None,
        proveedor_preferido: Optional[str] = None,
        modelo_preferido: Optional[str] = None,
        temperatura: float = 0.7,
        max_tokens: int = 2000,
    ) -> Dict[str, Any]:
        """
        Consulta un LLM externo con routing automático y fallback.
        
        Args:
            prompt: Pregunta o instrucción para el modelo
            criterio: "speed" (rápido), "code" (código), "context" (contexto largo), 
                      "privacy" (local/privado), "fallback" (robusto), "balanced" (equilibrado)
            system_prompt: Instrucciones de sistema opcionales
            proveedor_preferido: Forzar proveedor específico (ej: "Groq", "OpenRouter")
            modelo_preferido: Forzar modelo específico
            temperatura: 0.0-2.0 (creatividad)
            max_tokens: Longitud máxima respuesta
        Returns:
            Dict con provider, model, response, latency_ms, success
        """
        response = await llm_router.chat_with_retry(
            prompt=prompt,
            criteria=criterio,
            system_prompt=system_prompt,
            preferred_provider=proveedor_preferido,
            preferred_model=modelo_preferido,
            temperature=temperatura,
            max_tokens=max_tokens,
        )

        return {
            "proveedor": response.provider,
            "modelo": response.model,
            "respuesta": response.content,
            "latencia_ms": round(response.latency_ms, 2),
            "exito": response.success,
            "error": response.error,
        }

    @mcp.tool()
    async def listar_proveedores_llm(solo_configurados: bool = True) -> List[Dict[str, Any]]:
        """
        Lista proveedores LLM disponibles en el catálogo.
        
        Args:
            solo_configurados: Solo los que tienen API key o no la requieren
        """
        providers = catalog.get_configured_providers() if solo_configurados else catalog._providers_cache or {}
        if not providers:
            await catalog.get_providers()  # Force load
            providers = catalog.get_configured_providers() if solo_configurados else catalog._providers_cache or {}

        result = []
        for name, info in providers.items():
            metrics = catalog._metrics.get(name)
            result.append({
                "nombre": name,
                "categoria": info.category,
                "modelos": [{"id": m.id, "modality": m.modality, "context": m.context} for m in info.models],
                "requiere_api_key": not info.no_key_required,
                "api_key_configurada": bool(info.api_key),
                "tags": info._enriched.get("tags", []),
                "best_for": info._enriched.get("best_for", []),
                "descripcion": info._enriched.get("description", ""),
                "metricas": {
                    "exitos": metrics.success if metrics else 0,
                    "errores": metrics.errors if metrics else 0,
                    "tasa_error": metrics.error_rate if metrics else 0,
                    "latencia_promedio_ms": metrics.avg_latency if metrics else 0,
                } if metrics else None,
            })
        return result

    @mcp.tool()
    async def info_proveedor_llm(nombre: str) -> Optional[Dict[str, Any]]:
        """
        Información detallada de un proveedor específico.
        
        Args:
            nombre: Nombre del proveedor (ej: "Groq", "OpenRouter", "Google Gemini")
        """
        info = catalog.get_provider_info(nombre)
        if not info:
            return None

        metrics = catalog._metrics.get(nombre)
        return {
            "nombre": info.name,
            "base_url": info.baseUrl,
            "categoria": info.category,
            "modelos": [{"id": m.id, "modality": m.modality, "context": m.context} for m in info.models],
            "requiere_api_key": not info.no_key_required,
            "api_key_configurada": bool(info.api_key),
            "env_var": info.env_var,
            "enriquecido": info._enriched,
            "metricas": {
                "exitos": metrics.success if metrics else 0,
                "errores": metrics.errors if metrics else 0,
                "tasa_error": metrics.error_rate if metrics else 0,
                "latencia_promedio_ms": metrics.avg_latency if metrics else 0,
            } if metrics else None,
        }

    @mcp.tool()
    async def catalogo_modelos_stats() -> Dict[str, Any]:
        """
        Estadísticas del catálogo de modelos y métricas de uso.
        """
        providers = catalog.get_configured_providers()
        total_models = sum(len(p.models) for p in providers.values())
        by_category = {}
        for p in providers.values():
            by_category[p.category] = by_category.get(p.category, 0) + 1

        return {
            "proveedores_configurados": len(providers),
            "total_modelos": total_models,
            "por_categoria": by_category,
            "metricas_globales": catalog.get_metrics(),
            "cache_ttl_segundos": catalog.settings.cache_ttl,
            "ultima_actualizacion": catalog._last_cache_time,
        }