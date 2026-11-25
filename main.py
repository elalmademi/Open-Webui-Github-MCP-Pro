#!/usr/bin/env python3
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from types import SimpleNamespace

from mcp.server.fastmcp import FastMCP
from starlette.responses import Response

# Config & Settings
from config.settings import get_settings, Settings

# Services
from services.github_service import GitHubService
from services.catalog_service import CatalogService
from services.local_fs_service import LocalFSService
from services.llm_router import LLMRouter
from services.device_registry import DeviceRegistry
from services.appium_manager import AppiumManager
from services.maestro_runner import MaestroRunner

# Tools Registration
from tools.github_tools import register_github_tools
from tools.local_tools import register_local_tools
from tools.llm_tools import register_llm_tools
from tools.mobile_tools import register_mobile_tools

# Middleware
from middleware.logging import setup_structured_logging, get_logger


class ServiceContainer:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.logger = get_logger("mcp.container")
        self.github = None
        self.catalog = None
        self.local_fs = None
        self.llm_router = None
        self.device_registry = None
        self.appium_manager = None
        self.maestro_runner = None
        self._http_client = None

    async def initialize(self) -> None:
        self.logger.info("Inicializando servicios Pro...")

        # GitHub Service
        self.github = GitHubService(
            token=self.settings.github_token,
            timeout=self.settings.github_timeout,
            max_retries=self.settings.github_max_retries
        )
        await self.github._initialize()  # ← FIX: Inicializar y validar token

        # Catalog Service
        self.catalog = CatalogService(self.settings)
        await self.catalog.initialize()

        # Local FS Service
        self.local_fs = LocalFSService(self.settings)

        # HTTP Client para LLM Router
        import httpx
        self._http_client = httpx.AsyncClient(timeout=self.settings.llm_request_timeout)

        # LLM Router
        self.llm_router = LLMRouter(
            catalog=self.catalog,
            settings=self.settings,
            http_client=self._http_client
        )
        await self.llm_router.initialize()

        # Device Registry
        self.device_registry = DeviceRegistry(self.settings)
        await self.device_registry.initialize()

        # Appium Manager
        self.appium_manager = AppiumManager(self.settings)
        await self.appium_manager.initialize()

        # Maestro Runner
        self.maestro_runner = MaestroRunner(self.settings)
        await self.maestro_runner.initialize()

        self.logger.info("✅ Todos los servicios Pro inicializados correctamente")

    async def shutdown(self) -> None:
        self.logger.info("Cerrando servicios...")
        tasks = []

        if self.maestro_runner:
            tasks.append(self.maestro_runner.shutdown())
        if self.appium_manager:
            tasks.append(self.appium_manager.shutdown())
        if self.device_registry:
            tasks.append(self.device_registry.shutdown())
        if self.llm_router:
            tasks.append(self.llm_router.shutdown())
        if self.catalog:
            tasks.append(self.catalog.shutdown())
        if self.github:
            tasks.append(self.github._shutdown())  # ← FIX: Cerrar GitHub service
        if self._http_client:
            tasks.append(self._http_client.aclose())

        await asyncio.gather(*tasks, return_exceptions=True)


@asynccontextmanager
async def lifespan(app: FastMCP) -> AsyncGenerator[None, None]:
    app.state = SimpleNamespace()
    settings = get_settings()

    setup_structured_logging(
        level=settings.log_level,
        format=settings.log_format,
        loggers={"github": "INFO", "mcp": "DEBUG" if settings.debug else "INFO"}
    )

    container = ServiceContainer(settings)
    await container.initialize()
    app.state.container = container

    logger = get_logger("mcp.lifespan")
    logger.info("Registrando herramientas MCP...")

    register_github_tools(app, container.github)
    register_local_tools(app, container.local_fs)
    register_llm_tools(app, container.catalog, container.llm_router)
    register_mobile_tools(
        app,
        container.device_registry,
        container.appium_manager,
        container.maestro_runner
    )

    logger.info("✅ Todas las herramientas MCP registradas")

    try:
        yield
    finally:
        await container.shutdown()


settings = get_settings()
mcp = FastMCP(name=settings.app_name, lifespan=lifespan)

# Health check NATIVO de FastMCP
@mcp.custom_route("/health", methods=["GET"])
async def health_check(request):
    return Response(content="OK", status_code=200)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(mcp.streamable_http_app(), host="0.0.0.0", port=8000)
