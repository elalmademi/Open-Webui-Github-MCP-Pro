"""
Paquete de Servicios - Inyección de dependencias centralizada.
"""
from .github_service import GitHubService
from .catalog_service import CatalogService
from .local_fs_service import LocalFSService
from .llm_router import LLMRouter
from .device_registry import DeviceRegistry
from .appium_manager import AppiumManager
from .maestro_runner import MaestroRunner

__all__ = [
    "GitHubService",
    "CatalogService",
    "LocalFSService",
    "LLMRouter",
    "DeviceRegistry",
    "AppiumManager",
    "MaestroRunner",
]