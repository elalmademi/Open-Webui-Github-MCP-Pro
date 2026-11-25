"""
GitHub Service - Wrapper PyGithub con retry logic, rate limit handling y tipado estricto.
"""
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Callable, Awaitable, List, Optional, TypeVar

from github import Auth, Github, GithubException
from github.Repository import Repository
from github.ContentFile import ContentFile

from config.settings import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T")

# ─── Exceptions ───


class GitHubRateLimitError(Exception):
    def __init__(self, reset_at: Optional[int] = None):
        self.reset_at = reset_at
        msg = "Límite de API GitHub alcanzado"
        if reset_at:
            msg += f". Reset: {time.ctime(reset_at)}"
        super().__init__(msg)


class GitHubAuthError(Exception):
    pass


class GitHubNotFoundError(Exception):
    pass


class GitHubForbiddenError(Exception):
    pass


class GitHubValidationError(Exception):
    pass


# ─── Data Classes ───


@dataclass(frozen=True)
class RepoSummary:
    nombre: str
    estrellas: int
    descripcion: Optional[str] = None
    lenguaje: Optional[str] = None
    url: str = ""


@dataclass(frozen=True)
class FileContent:
    path: str
    content: str
    size: int
    encoding: str = "utf-8"


@dataclass(frozen=True)
class IssueSummary:
    numero: int
    titulo: str
    estado: str
    url: str
    autor: str = ""
    labels: List[str] = None

    def __post_init__(self):
        if self.labels is None:
            self.labels = []


@dataclass(frozen=True)
class CodeSearchResult:
    archivo: str
    repositorio: str
    url: str


# ─── Service ───


class GitHubService:
    """
    Servicio GitHub con:
    - Cliente sync (PyGithub) ejecutado en thread pool
    - Retry logic con exponential backoff
    - Rate limit handling automático
    - Logging estructurado
    """

    def __init__(self, token: Optional[str] = None, timeout: int = 30, max_retries: int = 3):
        self._token = token
        self._timeout = timeout
        self._max_retries = max_retries
        self._client: Optional[Github] = None
        self._authenticated_user: Optional[str] = None

    @asynccontextmanager
    async def lifespan(self) -> AsyncGenerator["GitHubService", None]:
        """Inicializa y cierra cliente GitHub."""
        await self._initialize()
        try:
            yield self
        finally:
            await self._shutdown()

    async def _initialize(self) -> None:
        """Crea cliente GitHub y valida auth."""
        loop = asyncio.get_event_loop()

        def _create_client() -> Github:
            if self._token:
                client = Github(auth=Auth.Token(self._token), timeout=self._timeout)
            else:
                client = Github(timeout=self._timeout)
            return client

        self._client = await loop.run_in_executor(None, _create_client)

        # Validar auth
        if self._token:
            try:
                user = await loop.run_in_executor(None, lambda: self._client.get_user().login)
                self._authenticated_user = user
                logger.info(f"GitHub autenticado como: {user}")
            except GithubException as e:
                logger.warning(f"GitHub token inválido, usando modo público: {e}")
                self._authenticated_user = None
        else:
            logger.warning("GITHUB_TOKEN no configurado - modo solo lectura pública (rate limit: 60/h)")

    async def _shutdown(self) -> None:
        """Cierra recursos (PyGithub no requiere close explícito)."""
        self._client = None

    # ─── Retry Logic ───

    async def _execute_with_retry(
        self,
        operation: Callable[[], Awaitable[T]],
        operation_name: str = "GitHub operation"
    ) -> T:
        """Ejecuta operación con retry, rate limit handling y logging."""
        last_exc = None

        for attempt in range(self._max_retries):
            try:
                return await operation()
            except GithubException as e:
                last_exc = e
                status = e.status
                data = e.data or {}
                headers = getattr(e, "headers", {}) or {}

                if status == 401:
                    raise GitHubAuthError(data.get("message", "Credenciales inválidas"))
                if status == 404:
                    raise GitHubNotFoundError(data.get("message", "Recurso no existe"))
                if status == 422:
                    raise GitHubValidationError(data.get("errors", []))
                if status == 403:
                    # Rate limit o forbidden
                    reset_header = headers.get("X-RateLimit-Reset") or headers.get("x-ratelimit-reset")
                    if reset_header and reset_header.isdigit():
                        reset_at = int(reset_header)
                        wait = max(1, reset_at - int(time.time()) + 2)
                        logger.warning(
                            f"Rate limit GitHub en {operation_name}. "
                            f"Esperando {wait}s (intento {attempt + 1}/{self._max_retries})"
                        )
                        await asyncio.sleep(wait)
                        continue
                    reason = data.get("message", "Acceso denegado")
                    if isinstance(data.get("errors"), list):
                        reason = "; ".join(err.get("message", "") for err in data["errors"])
                    raise GitHubForbiddenError(reason)
                if status == 429:
                    retry_after = headers.get("Retry-After")
                    wait = int(retry_after) if retry_after and retry_after.isdigit() else 2 ** (attempt + 1)
                    logger.warning(f"429 GitHub en {operation_name}. Backoff {wait}s")
                    await asyncio.sleep(wait)
                    continue
                if 500 <= status < 600:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise
            except Exception as e:
                last_exc = e
                if attempt == self._max_retries - 1:
                    raise
                await asyncio.sleep(2 ** attempt)

        raise RuntimeError(f"{operation_name} falló tras {self._max_retries} intentos: {last_exc}")

    # ─── Public API ───

    async def search_repositories(self, query: str, limit: int = 5) -> List[RepoSummary]:
        """Busca repositorios por query."""

        async def _search() -> List[RepoSummary]:
            repos = self._client.search_repositories(query=query)
            results = []
            for i, repo in enumerate(repos):
                if i >= limit:
                    break
                results.append(RepoSummary(
                    nombre=repo.full_name,
                    estrellas=repo.stargazers_count,
                    descripcion=repo.description,
                    lenguaje=repo.language,
                    url=repo.html_url,
                ))
            return results

        return await self._execute_with_retry(_search, "search_repositories")

    async def get_repo_contents(self, repo_name: str, path: str = "") -> List[FileContent]:
        """Lista contenido de un directorio en repo."""

        async def _list() -> List[FileContent]:
            repo = self._client.get_repo(repo_name)
            contents = repo.get_contents(path)
            if not isinstance(contents, list):
                contents = [contents]
            results = []
            for item in contents:
                if item.type == "file":
                    content = item.decoded_content.decode("utf-8", errors="replace")
                    results.append(FileContent(
                        path=item.path,
                        content=content,
                        size=item.size,
                    ))
            return results

        return await self._execute_with_retry(_list, f"get_repo_contents:{repo_name}")

    async def get_file_content(self, repo_name: str, path: str) -> FileContent:
        """Obtiene contenido de un archivo específico."""

        async def _read() -> FileContent:
            repo = self._client.get_repo(repo_name)
            file_content = repo.get_contents(path)
            if isinstance(file_content, list):
                raise GitHubValidationError([{"message": f"Path {path} es un directorio"}])
            content = file_content.decoded_content.decode("utf-8", errors="replace")
            return FileContent(
                path=file_content.path,
                content=content,
                size=file_content.size,
            )

        return await self._execute_with_retry(_read, f"get_file:{repo_name}/{path}")

    async def list_issues(
        self,
        repo_name: str,
        state: str = "open",
        limit: int = 10
    ) -> List[IssueSummary]:
        """Lista issues de un repositorio."""

        async def _list() -> List[IssueSummary]:
            repo = self._client.get_repo(repo_name)
            issues = repo.get_issues(state=state)
            results = []
            for i, issue in enumerate(issues):
                if i >= limit:
                    break
                results.append(IssueSummary(
                    numero=issue.number,
                    titulo=issue.title,
                    estado=issue.state,
                    url=issue.html_url,
                    autor=issue.user.login if issue.user else "",
                    labels=[l.name for l in issue.labels] if issue.labels else [],
                ))
            return results

        return await self._execute_with_retry(_list, f"list_issues:{repo_name}")

    async def create_issue(self, repo_name: str, title: str, body: str) -> str:
        """Crea un issue en el repositorio."""

        async def _create() -> str:
            repo = self._client.get_repo(repo_name)
            issue = repo.create_issue(title=title, body=body)
            return issue.html_url

        return await self._execute_with_retry(_create, f"create_issue:{repo_name}")

    async def search_code(self, query: str, limit: int = 5) -> List[CodeSearchResult]:
        """Busca código en GitHub."""

        async def _search() -> List[CodeSearchResult]:
            results = self._client.search_code(query=query)
            snippets = []
            for i, file in enumerate(results):
                if i >= limit:
                    break
                snippets.append(CodeSearchResult(
                    archivo=file.path,
                    repositorio=file.repository.full_name,
                    url=file.html_url,
                ))
            return snippets

        return await self._execute_with_retry(_search, "search_code")

    @property
    def is_authenticated(self) -> bool:
        return self._authenticated_user is not None

    @property
    def authenticated_user(self) -> Optional[str]:
        return self._authenticated_user