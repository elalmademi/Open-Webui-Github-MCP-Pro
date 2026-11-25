"""
GitHub Tools MCP - Tools para búsqueda y gestión de repositorios GitHub.
"""
from typing import List, Optional

from mcp.server.fastmcp import FastMCP

from services.github_service import GitHubService, RepoSummary, FileContent, IssueSummary, CodeSearchResult


def register_github_tools(mcp: FastMCP, github_service: GitHubService):
    """Registra todas las tools GitHub en el servidor MCP."""

    @mcp.tool()
    async def buscar_repo(query: str, limit: int = 5) -> List[RepoSummary]:
        """
        Busca repositorios en GitHub por query.
        
        Args:
            query: Término de búsqueda (ej: "machine learning python", "user:octocat stars:>1000")
            limit: Máximo resultados (default: 5, max: 20)
        """
        if limit > 20:
            limit = 20
        return await github_service.search_repositories(query, limit)

    @mcp.tool()
    async def mapear_repositorio(repo: str, ruta: str = "") -> List[FileContent]:
        """
        Lista contenido de un directorio en un repositorio GitHub.
        
        Args:
            repo: Nombre completo del repo (ej: "octocat/Hello-World")
            ruta: Ruta del directorio (vacío = root)
        """
        return await github_service.get_repo_contents(repo, ruta)

    @mcp.tool()
    async def leer_archivo(repo: str, ruta: str) -> FileContent:
        """
        Lee el contenido de un archivo en un repositorio GitHub.
        
        Args:
            repo: Nombre completo del repo (ej: "octocat/Hello-World")
            ruta: Ruta al archivo (ej: "src/main.py")
        """
        return await github_service.get_file_content(repo, ruta)

    @mcp.tool()
    async def listar_issues(
        repo: str,
        estado: str = "open",
        limite: int = 10
    ) -> List[IssueSummary]:
        """
        Lista issues de un repositorio GitHub.
        
        Args:
            repo: Nombre completo del repo (ej: "octocat/Hello-World")
            estado: "open", "closed" o "all" (default: "open")
            limite: Máximo issues a retornar (default: 10, max: 100)
        """
        if limite > 100:
            limite = 100
        return await github_service.list_issues(repo, estado, limite)

    @mcp.tool()
    async def crear_issue(repo: str, titulo: str, cuerpo: str) -> str:
        """
        Crea un issue en un repositorio GitHub.
        
        Args:
            repo: Nombre completo del repo (ej: "octocat/Hello-World")
            titulo: Título del issue
            cuerpo: Descripción detallada (Markdown soportado)
        Returns:
            URL del issue creado
        """
        return await github_service.create_issue(repo, titulo, cuerpo)

    @mcp.tool()
    async def buscar_codigo(query: str, limit: int = 5) -> List[CodeSearchResult]:
        """
        Busca código en GitHub (GitHub Code Search).
        
        Args:
            query: Query de búsqueda (ej: "function authenticate language:python repo:org/repo")
            limit: Máximo resultados (default: 5, max: 20)
        """
        if limit > 20:
            limit = 20
        return await github_service.search_code(query, limit)

    @mcp.tool()
    async def github_status() -> dict:
        """
        Retorna estado de la conexión GitHub.
        """
        return {
            "authenticated": github_service.is_authenticated,
            "user": github_service.authenticated_user,
            "rate_limit_note": "Sin token: 60 req/h | Con token: 5000 req/h"
        }