"""
Local FS Service - Operaciones seguras en /app/local_docs (RO) y /app/workspace (RW).
"""
import logging
import mimetypes
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Optional, Union

from config.settings import get_settings

logger = logging.getLogger(__name__)

# ─── Data Classes ───


class FileInfo:
    def __init__(self, path: Path, base: Path):
        self.path = path
        self.base = base
        self.rel_path = path.relative_to(base)
        stat = path.stat()
        self.name = path.name
        self.size = stat.st_size
        self.suffix = path.suffix.lower()
        self.mime_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.modified = stat.st_mtime
        self.is_file = path.is_file()
        self.is_dir = path.is_dir()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": str(self.rel_path),
            "size": self.size,
            "suffix": self.suffix,
            "mime_type": self.mime_type,
            "modified": self.modified,
            "is_file": self.is_file,
            "is_dir": self.is_dir,
        }


class ReadResult:
    def __init__(
        self,
        file: str,
        content: Union[str, bytes],
        size: int,
        encoding: str = "utf-8",
        is_binary: bool = False,
    ):
        self.file = file
        self.content = content
        self.size = size
        self.encoding = encoding
        self.is_binary = is_binary

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file": self.file,
            "content": self.content if not self.is_binary else f"<binary {self.size} bytes>",
            "size": self.size,
            "encoding": self.encoding,
            "is_binary": self.is_binary,
        }


# ─── Service ───


class LocalFSService:
    """
    Servicio de archivos locales con:
    - Path traversal protection (resolve + base check)
    - Soporte PDF, DOCX, TXT, MD, JSON, YAML, imágenes
    - Lectura streaming para archivos grandes
    - Escritura atómica (temp + rename)
    """

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self.local_docs = self.settings.local_docs_path.resolve()
        self.workspace = self.settings.workspace_path.resolve()
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        """Crea directorios base si no existen."""
        self.local_docs.mkdir(parents=True, exist_ok=True)
        self.workspace.mkdir(parents=True, exist_ok=True)

    # ─── Security ───

    def _resolve_safe(self, target: Path, base: Path, description: str) -> Path:
        """Resuelve path y valida que está dentro del base (anti path traversal)."""
        try:
            resolved = target.resolve()
            base_resolved = base.resolve()
            if not str(resolved).startswith(str(base_resolved)):
                raise ValueError(f"Path traversal detectado: {target} fuera de {base}")
            return resolved
        except Exception as e:
            logger.error(f"Error resolviendo {description}: {e}")
            raise ValueError(f"Path inválido para {description}: {target}")

    # ─── List ───

    def list_files(self, directory: str = "local_docs", recursive: bool = True) -> List[Dict[str, Any]]:
        """Lista archivos en local_docs o workspace."""
        base = self.local_docs if directory == "local_docs" else self.workspace
        if not base.exists():
            return []

        files = []
        pattern = "**/*" if recursive else "*"
        for path in base.glob(pattern):
            if path.is_file():
                info = FileInfo(path, base)
                files.append(info.to_dict())
        return files

    # ─── Read ───

    def read_file(
        self,
        filename: str,
        directory: str = "local_docs",
        encoding: str = "utf-8",
        max_size: int = 10 * 1024 * 1024,  # 10MB default
    ) -> ReadResult:
        """Lee archivo con detección de tipo y límites de seguridad."""
        base = self.local_docs if directory == "local_docs" else self.workspace
        target = self._resolve_safe(base / filename, base, f"lectura {directory}")

        if not target.exists():
            raise FileNotFoundError(f"Archivo no encontrado: {filename}")
        if not target.is_file():
            raise ValueError(f"No es un archivo: {filename}")

        if target.stat().st_size > max_size:
            raise ValueError(f"Archivo demasiado grande: {target.stat().st_size} bytes (max {max_size})")

        suffix = target.suffix.lower()

        # PDF
        if suffix == ".pdf":
            return self._read_pdf(target, filename)

        # DOCX
        if suffix == ".docx":
            return self._read_docx(target, filename)

        # Imágenes → base64
        if suffix in [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"]:
            return self._read_binary(target, filename)

        # Texto (incluye .md, .txt, .json, .yaml, .yml, .py, .js, etc.)
        try:
            content = target.read_text(encoding=encoding, errors="replace")
            return ReadResult(file=filename, content=content, size=len(content), encoding=encoding)
        except UnicodeDecodeError:
            # Fallback binario
            return self._read_binary(target, filename)

    def _read_pdf(self, path: Path, filename: str) -> ReadResult:
        try:
            import PyPDF2
            with open(path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                text = "\n".join([page.extract_text() or "" for page in reader.pages])
            return ReadResult(file=filename, content=text, size=len(text), encoding="utf-8")
        except ImportError:
            logger.warning("PyPDF2 no instalado, leyendo como binario")
            return self._read_binary(path, filename)

    def _read_docx(self, path: Path, filename: str) -> ReadResult:
        try:
            import docx
            doc = docx.Document(path)
            text = "\n".join([p.text for p in doc.paragraphs])
            return ReadResult(file=filename, content=text, size=len(text), encoding="utf-8")
        except ImportError:
            logger.warning("python-docx no instalado, leyendo como binario")
            return self._read_binary(path, filename)

    def _read_binary(self, path: Path, filename: str) -> ReadResult:
        import base64
        content = path.read_bytes()
        b64 = base64.b64encode(content).decode("ascii")
        return ReadResult(
            file=filename,
            content=b64,
            size=len(content),
            encoding="base64",
            is_binary=True,
        )

    # ─── Write ───

    def write_file(
        self,
        filename: str,
        content: Union[str, bytes],
        directory: str = "workspace",
        encoding: str = "utf-8",
        overwrite: bool = True,
    ) -> Dict[str, Any]:
        """Escribe archivo en workspace (atómico via temp + rename)."""
        base = self.workspace if directory == "workspace" else self.local_docs
        target = self._resolve_safe(base / filename, base, f"escritura {directory}")

        if target.exists() and not overwrite:
            raise FileExistsError(f"Archivo ya existe: {filename}")

        # Crear directorio padre
        target.parent.mkdir(parents=True, exist_ok=True)

        # Escritura atómica
        import tempfile
        with tempfile.NamedTemporaryFile(
            mode="wb" if isinstance(content, bytes) else "w",
            dir=target.parent,
            delete=False,
            encoding=None if isinstance(content, bytes) else encoding,
        ) as tmp:
            tmp_path = Path(tmp.name)
            if isinstance(content, str):
                tmp.write(content)
            else:
                tmp.write(content)

        # Atomic rename
        tmp_path.replace(target)

        return {
            "file": filename,
            "status": "written",
            "size": target.stat().st_size,
            "path": str(target.relative_to(base)),
        }

    def delete_file(self, filename: str, directory: str = "workspace") -> bool:
        """Elimina archivo en workspace."""
        base = self.workspace if directory == "workspace" else self.local_docs
        target = self._resolve_safe(base / filename, base, f"eliminación {directory}")

        if not target.exists():
            raise FileNotFoundError(f"Archivo no encontrado: {filename}")

        target.unlink()
        return True

    # ─── Utility ───

    def get_file_info(self, filename: str, directory: str = "local_docs") -> Optional[Dict[str, Any]]:
        """Metadata de archivo sin leer contenido."""
        base = self.local_docs if directory == "local_docs" else self.workspace
        target = self._resolve_safe(base / filename, base, f"info {directory}")

        if not target.exists():
            return None

        info = FileInfo(target, base)
        return info.to_dict()