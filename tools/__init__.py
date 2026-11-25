"""
Paquete de Tools MCP - Registro centralizado de todas las tools.
"""
from .github_tools import register_github_tools
from .local_tools import register_local_tools
from .llm_tools import register_llm_tools
from .mobile_tools import register_mobile_tools

__all__ = [
    "register_github_tools",
    "register_local_tools",
    "register_llm_tools",
    "register_mobile_tools",
]