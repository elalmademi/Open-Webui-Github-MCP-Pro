# 📘 Manual Maestro: Infraestructura GitHub MCP Server Pro

## 1. Identidad del Sistema
Este sistema es un entorno de ingeniería autónoma basado en el **Model Context Protocol (MCP)**. Permite que un LLM interactúe con repositorios de GitHub, procese documentos locales y gestione un espacio de trabajo en el disco duro del usuario.

## 2. Mapa de Infraestructura (Arquitectura)
### 📦 Orquestación (Docker)
- **Archivo de Configuración:** `docker-compose.local.yml`
- **Comando de despliegue:** `docker compose -f docker-compose.local.yml up -d --build`
- **Red:** `dev-net` (Bridge)
- **Volúmenes Críticos:** 
  - `openwebui_data` (Externo: `openwebui-mcp-cloud_openwebui_data`) $\rightarrow$ Contiene la base de datos `webui.db`.
  - `/app/local_docs` $\rightarrow$ Montado desde `C:/Users/Alejandro/Documents/IA/Documentos` (Read-Only).
  - `/app/workspace` $\rightarrow$ Montado desde `C:/Users/Alejandro/Documents/IA/Workspace` (Read-Write).

### 🚀 Servicios y Puertos
- **Open WebUI:** `open-webui-dev` | Puerto `8080` | Imagen: `ghcr.io/open-webui/open-webui`
- **MCP Server:** `mcp-github-server` | Puerto `8888` | Imagen: Local (construida desde Dockerfile)

## 3. Matriz de Dependencias Críticas
- **Lenguaje:** Python 3.11-slim.
- **Librería MCP:** **ESTRICTAMENTE `mcp<2`**. (Cualquier versión $\ge 2.0$ rompe la importación de `FastMCP`).
- **GitHub API:** Usa `PyGithub` (para evitar dependencias de C++ en Windows).
- **Framework API:** FastAPI + Uvicorn.

## 4. Diccionario de Herramientas (Toolbox)
El servidor MCP expone las siguientes capacidades técnicas:

### 📂 Gestión Local
- `listar_archivos_locales`: Lista archivos en `/app/local_docs`.
- `leer_local`: Procesa `.pdf`, `.docx`, `.txt` y `.md`.
- `escribir_archivo_local`: Crea/edita archivos en `/app/workspace`.
- `ejecutar_comando`: Ejecuta comandos de shell en el workspace.

### 🐙 GitHub Engine
- `buscar_repo` / `mapear_repositorio`: Navegación y estructura de repositorios.
- `leer_archivo`: Extracción de código fuente.
- `analizar_historial_commits`: Arqueología de código y autoría.
- `listar_issues` / `crear_issue`: Gestión de tickets profesional.
- `buscar_codigo`: Búsqueda global de snippets.

### 🌐 Inteligencia Externa
- `buscar_modelo_gratis`: Encuentra el mejor LLM gratuito según criterio (velocidad, contexto, código).
- `consultar_llm_externo`: Consulta modelos vía OpenRouter y otros proveedores.

## 5. Protocolos de Emergencia (Troubleshooting)
| Síntoma | Causa Probable | Solución Obligatoria |
| :--- | :--- | :--- |
| **"Usuario no encontrado"** | Migración de DB o sesión corrupta | 1. Modo Incógnito $\rightarrow$ 2. `ENABLE_SIGNUP=true` $\rightarrow$ 3. Nuevo usuario $\rightarrow$ 4. Asignar Admin al usuario antiguo. |
| **`ModuleNotFoundError: fastmcp`** | Instalación de `mcp` v2.0+ | Actualizar `requirements.txt` a `mcp<2` y ejecutar `docker compose -f docker-compose.local.yml up -d --build`. |
| **`Conflict. Container name...`** | Contenedores huérfanos | `docker rm -f open-webui-dev mcp-github-server mcpo-openwebui-dev mcp-server-dev` |
| **`unknown option --host`** | Error de sintaxis en CMD | Asegurar que el archivo `.py` esté antes de los argumentos `--host` en el Dockerfile. |

***
