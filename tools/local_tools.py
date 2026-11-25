"""
Local Tools MCP - Tools para gestión de archivos locales (/app/local_docs RO, /app/workspace RW).
"""
import base64
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from mcp.server.fastmcp import FastMCP, Image

from services.local_fs_service import LocalFSService, FileInfo, ReadResult


def register_local_tools(mcp: FastMCP, fs_service: LocalFSService):
    """Registra tools de sistema de archivos local."""

    @mcp.tool()
    async def listar_archivos_locales(
        directorio: str = "local_docs",
        recursive: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Lista archivos en directorio local.
        
        Args:
            directorio: "local_docs" (solo lectura) o "workspace" (lectura/escritura)
            recursive: Buscar recursivamente en subdirectorios
        """
        return fs_service.list_files(directorio, recursive)

    @mcp.tool()
    async def leer_local(
        nombre_archivo: str,
        directorio: str = "local_docs",
        encoding: str = "utf-8"
    ) -> Dict[str, Any]:
        """
        Lee un archivo local (PDF, DOCX, TXT, MD, JSON, imágenes, etc.).
        
        Args:
            nombre_archivo: Nombre del archivo (relativo al directorio base)
            directorio: "local_docs" o "workspace"
            encoding: Encoding para archivos de texto
        Returns:
            Dict con file, content, size, encoding, is_binary
        """
        result = fs_service.read_file(nombre_archivo, directorio, encoding)
        return result.to_dict()

    @mcp.tool()
    async def escribir_archivo_local(
        ruta: str,
        contenido: Union[str, bytes],
        directorio: str = "workspace",
        encoding: str = "utf-8",
        overwrite: bool = True
    ) -> Dict[str, Any]:
        """
        Escribe un archivo en el workspace (escritura atómica).
        
        Args:
            ruta: Ruta relativa dentro del workspace
            contenido: Texto o bytes a escribir
            directorio: "workspace" (solo workspace permitido para escritura)
            encoding: Encoding si contenido es string
            overwrite: Sobrescribir si existe
        """
        if directorio != "workspace":
            raise ValueError("Escritura solo permitida en 'workspace'")

        # Detectar si es base64
        if isinstance(contenido, str) and contenido.startswith("data:"):
            # Data URL: data:image/png;base64,...
            header, b64data = contenido.split(",", 1)
            contenido = base64.b64decode(b64data)

        return fs_service.write_file(ruta, contenido, directorio, encoding, overwrite)

    @mcp.tool()
    async def eliminar_archivo_local(ruta: str, directorio: str = "workspace") -> bool:
        """
        Elimina un archivo en el workspace.
        
        Args:
            ruta: Ruta relativa al archivo
            directorio: "workspace" (solo workspace)
        """
        if directorio != "workspace":
            raise ValueError("Eliminación solo permitida en 'workspace'")
        return fs_service.delete_file(ruta, directorio)

    @mcp.tool()
    async def info_archivo_local(nombre_archivo: str, directorio: str = "local_docs") -> Optional[Dict[str, Any]]:
        """
        Obtiene metadata de un archivo sin leer su contenido.
        
        Args:
            nombre_archivo: Nombre del archivo
            directorio: "local_docs" o "workspace"
        """
        return fs_service.get_file_info(nombre_archivo, directorio)

    @mcp.tool()
    async def leer_imagen_como_base64(nombre_archivo: str, directorio: str = "local_docs") -> Image:
        """
        Lee una imagen y la retorna como objeto Image MCP (para visualización en chat).
        
        Args:
            nombre_archivo: Nombre del archivo de imagen
            directorio: "local_docs" o "workspace"
        """
        result = fs_service.read_file(nombre_archivo, directorio)
        if not result.is_binary:
            raise ValueError(f"Archivo no es imagen binaria: {nombre_archivo}")
        
        # El content ya es base64 string
        return Image(data=result.content, format=result.encoding.replace("base64", "").strip(".") or "png")