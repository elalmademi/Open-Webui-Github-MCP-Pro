# 📘 Manual Maestro de Infraestructura: GitHub MCP Server Pro
**Versión:** 1.0.0 | **Estado:** Producción Validada | **Fecha:** 2025
**Autor:** Ingeniería de Infraestructura MCP Pro
**Clasificación:** Documento Técnico - Única Fuente de Verdad

---

## 1. Visión General de la Arquitectura

### 1.1 Descripción del Sistema
El **GitHub MCP Server Pro** es un servidor **Model Context Protocol (MCP) nativo** implementado en Python 3.11 que actúa como capa de orquestación unificada entre **Open WebUI** y un ecosistema de herramientas de ingeniería. El sistema expone capacidades de **GitHub API**, **Sistema de Archivos Local**, **Testing Móvil (Appium/Maestro)**, **Routing de LLMs Externos** y **Gestión de Conocimiento** a través de una interfaz estandarizada MCP sobre HTTP/SSE.

**Componentes Orquestados:**
- 🐙 **GitHub Engine** - API REST/GraphQL completa via PyGithub
- 📂 **Local FS Manager** - Lectura/escritura sandboxed en volumes Docker
- 📱 **Mobile Testing Lab** - Appium + Maestro + Device Farms (BrowserStack, SauceLabs, LambdaTest, Firebase)
- 🌐 **LLM Router** - Multi-proveedor (Groq, OpenRouter, Google Gemini, Ollama) con fallback automático
- 🧠 **Knowledge Base** - Búsqueda semántica y exacta sobre documentos locales

### 1.2 Diagrama Conceptual del Flujo de Datos

```mermaid
flowchart LR
    A[Open WebUI<br/>v0.13.5+] -->|SSE/JSON-RPC<br/>HTTP 8000| B[FastMCP Server<br/>Python 3.11]
    B --> C{Service Container}
    C --> D[GitHub API<br/>PyGithub]
    C --> E[Local FS<br/>/app/workspace<br/>/app/local_docs]
    C --> F[Appium Server<br/>Maestro Flows]
    C --> G[LLM Providers<br/>Groq/OpenRouter/Gemini]
    C --> H[Vector DB<br/>ChromaDB/SQLite]
    
    style A fill:#1f77b4,color:#fff
    style B fill:#ff7f0e,color:#fff
    style C fill:#2ca02c,color:#fff
    style D fill:#d62728,color:#fff
    style E fill:#9467bd,color:#fff
    style F fill:#8c564b,color:#fff
    style G fill:#e377c2,color:#fff
    style H fill:#7f7f7f,color:#fff
```

**Protocolo de Comunicación:**
- **Transporte:** `streamable-http` (MCP 2024-11-05 spec)
- **Endpoint:** `http://mcp-github-server:8000/mcp`
- **Autenticación:** Bearer Token via Header `Authorization` (configurable)
- **Formato:** JSON-RPC 2.0 sobre Server-Sent Events (SSE)

---

## 2. Especificaciones Técnicas (El "Blindaje")

### 2.1 Versiones Críticas - **NO MODIFICAR SIN PRUEBA DE REGRESIÓN COMPLETA**

| Dependencia | Versión Obligatoria | Justificación Técnica |
|-------------|---------------------|----------------------|
| **mcp** | `==1.6.0` | **CRÍTICO**: `mcp>=2.0.0` rompe `FastMCP` import (`AttributeError: module 'mcp' has no attribute 'FastMCP'`). Cambio breaking en API pública. |
| **pydantic** | `==2.9.2` | **CRÍTICO**: `pydantic>=2.10` introduce cambios en `BaseModel` que rompen validación de herramientas MCP. `pydantic<2.9` carece de `model_rebuild()` necesario para schemas dinámicos. |
| **fastapi** | `==0.110.1` | Compatibilidad probada con `pydantic==2.9.2` y `starlette==0.37.2` |
| **uvicorn** | `==0.29.0` | Worker `uvloop` + `httptools` para rendimiento SSE |
| **pygithub** | `==2.6.1` | Evita dependencias C++ (crítico en Windows/Alpine) |
| **python-socketio** | `==5.10.0` | Requerido para `streamable-http` transport |

### 2.2 Red y Puertos

```yaml
# Configuración de Red Inmutable
services:
  mcp-github-server:
    ports:
      - "8000:8000"        # Puerto único: interno=externo=8000
    environment:
      - HOST=0.0.0.0       # Bind obligatorio para acceso externo Docker
      - PORT=8000
    networks:
      - dev-net            # Red bridge aislada
```

**Regla de Oro:** El puerto **8000** es inmutable. Cambiarlo requiere actualización coordinada en:
1. `docker-compose.local.yml`
2. Configuración Open WebUI (`/mcp` endpoint)
3. Variables de entorno del contenedor
4. Healthcheck endpoint

### 2.3 Transporte MCP: `streamable-http`

```python
# Configuración obligatoria en main.py
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    name="github-mcp-server-pro",
    host="0.0.0.0",
    port=8000,
    # streamable-http es el único transporte soportado en producción
    sse_path="/mcp",           # Endpoint SSE
    message_path="/mcp/message" # Endpoint POST para cliente
)

# Ejecución bloqueante - NO usar uvicorn.run() ni FastAPI wrappers
if __name__ == "__main__":
    mcp.run(transport="streamable-http")
```

**Por qué `streamable-http` y NO `stdio`/`websocket`:**
- ✅ Compatible con Open WebUI v0.13.5+ nativo
- ✅ Permite múltiples clientes concurrentes
- ✅ Healthcheck HTTP nativo (`/health`)
- ✅ Funciona detrás de reverse proxies (nginx, traefik)
- ❌ `stdio`: Solo CLI, no escalable
- ❌ `websocket`: No soportado por spec MCP 2024-11-05

---

## 3. Guía de Despliegue Paso a Paso

### 3.1 Requisitos Previos
- Docker Engine 24.0+ / Docker Compose v2.20+
- GitHub Personal Access Token (Classic) con scopes: `repo`, `read:org`, `read:user`
- (Opcional) API Keys: `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY`

### 3.2 Configuración del `.env` (OBLIGATORIO)

```bash
# .env - Ubicación: raíz del proyecto (mismo nivel que docker-compose.local.yml)
# ⚠️ NUNCA commitear este archivo - Añadir a .gitignore

# === GITHUB (OBLIGATORIO) ===
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
# Token Classic con scopes: repo, read:org, read:user
# Validar: curl -H "Authorization: Bearer $GITHUB_TOKEN" https://api.github.com/rate_limit

# === LLM PROVIDERS (OPCIONALES - Para router inteligente) ===
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
GEMINI_API_KEY=AIzaSyxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
# OLLAMA_HOST=http://host.docker.internal:11434  # Si usas Ollama local

# === CONFIGURACIÓN SERVIDOR ===
MCP_SERVER_NAME=github-mcp-server-pro
MCP_HOST=0.0.0.0
MCP_PORT=8000
LOG_LEVEL=INFO

# === VOLUMES (AJUSTAR RUTAS LOCALES) ===
LOCAL_DOCS_PATH=/host/path/to/documents      # Read-Only
WORKSPACE_PATH=/host/path/to/workspace        # Read-Write
OPENWEBUI_DATA_VOLUME=openwebui-mcp-cloud_openwebui_data
```

### 3.3 `docker-compose.local.yml` - Configuración Canónica

```yaml
version: '3.8'

services:
  mcp-github-server:
    build:
      context: .
      dockerfile: Dockerfile
      args:
        - PYTHON_VERSION=3.11-slim
    container_name: mcp-github-server
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      - HOST=0.0.0.0
      - PORT=8000
    env_file:
      - .env
    volumes:
      - ${LOCAL_DOCS_PATH}:/app/local_docs:ro
      - ${WORKSPACE_PATH}:/app/workspace:rw
    networks:
      - dev-net
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

  # open-webui-dev se gestiona por separado (stack principal)
  # Este compose SOLO levanta el MCP Server

networks:
  dev-net:
    name: dev-net
    driver: bridge
    external: false

volumes:
  openwebui_data:
    name: ${OPENWEBUI_DATA_VOLUME}
    external: true
```

### 3.4 `Dockerfile` - Imagen de Producción

```dockerfile
# Dockerfile - Optimizado para Python 3.11 + MCP 1.6.0
ARG PYTHON_VERSION=3.11-slim
FROM python:${PYTHON_VERSION}

# Metadatos
LABEL maintainer="MCP Pro Engineering"
LABEL version="1.0.0"
LABEL description="GitHub MCP Server Pro - Production Image"

# Variables de entorno
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Dependencias del sistema (mínimas)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Usuario no-root
RUN groupadd -r mcpuser && useradd -r -g mcpuser mcpuser
WORKDIR /app

# Copiar requirements PRIMERO (cache layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código fuente
COPY main.py .
COPY src/ ./src/

# Permisos
RUN chown -R mcpuser:mcpuser /app
USER mcpuser

# Healthcheck endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Ejecución directa - CRÍTICO: main.py ANTES de flags
CMD ["python", "main.py"]
```

### 3.5 `requirements.txt` - Versiones Blindadas

```txt
# requirements.txt - Versiones EXACTAS probadas en producción
# NO usar >=, ~= ni ^ - Solo == para reproducibilidad absoluta

# Core MCP - CRÍTICO: mcp<2.0
mcp==1.6.0

# FastAPI Stack - Versiones compatibles con pydantic 2.9.2
fastapi==0.110.1
uvicorn[standard]==0.29.0
pydantic==2.9.2
pydantic-settings==2.3.4
starlette==0.37.2

# GitHub API - Sin dependencias C++
PyGithub==2.6.1

# HTTP Client
httpx==0.27.0
aiohttp==3.9.5

# LLM Providers
openai==1.30.1          # Para OpenRouter/Groq compat
google-generativeai==0.7.2

# Utilidades
python-dotenv==1.0.1
python-multipart==0.0.9
typing-extensions==4.11.0

# Testing Mobile (Lazy imports)
Appium-Python-Client==3.1.0
maestro==0.1.0
```

### 3.6 Comandos de Despliegue - Secuencia Obligatoria

```bash
# 1. LIMPIEZA TOTAL (Elimina contenedores, redes, volúmenes anónimos)
docker compose -f docker-compose.local.yml down -v --remove-orphans

# 2. BUILD FORZADO (Sin cache para garantizar versions)
docker compose -f docker-compose.local.yml build --no-cache

# 3. DESPLIEGUE EN SEGUNDO PLANO
docker compose -f docker-compose.local.yml up -d

# 4. VERIFICACIÓN DE LOGS (Esperar "Application startup complete")
docker compose -f docker-compose.local.yml logs -f mcp-github-server

# 5. HEALTHCHECK AUTOMÁTICO
curl -f http://localhost:8000/health
# Respuesta esperada: {"status":"healthy","server":"github-mcp-server-pro","version":"1.0.0"}
```

### 3.7 Verificación de Salud Completa

```bash
# Endpoint nativo de salud
curl -s http://localhost:8000/health | jq .

# Verificar herramientas registradas
curl -s http://localhost:8000/mcp/tools/list | jq .

# Test de autenticación GitHub
curl -s http://localhost:8000/mcp/call/github_status | jq .

# Test de sistema de archivos local
curl -s http://localhost:8000/mcp/call/listar_archivos_locales \
  -H "Content-Type: application/json" \
  -d '{"directorio": "local_docs", "recursive": true}' | jq .
```

**Criterios de Aceptación (Go/No-Go):**
- ✅ `health` returns `{"status":"healthy"}`
- ✅ `tools/list` retorna ≥15 herramientas
- ✅ `github_status` retorna `authenticated: true` + `rate_limit > 1000`
- ✅ `listar_archivos_locales` retorna array no vacío
- ✅ Logs muestran `Application startup complete` sin errores

---

## 4. Catálogo Detallado de Herramientas

### 4.1 Categoría: GitHub Engine (7 Herramientas)

| Herramienta | Descripción | Parámetros Clave | Retorno |
|-------------|-------------|------------------|---------|
| `github_status` | Estado conexión y rate limits | Ninguno | `authenticated`, `user`, `rate_limit` |
| `buscar_repo` | Búsqueda repositorios GitHub | `query` (str), `limit` (int, 1-20) | Array repos con stars, desc, language |
| `mapear_repositorio` | Estructura directorios repo | `repo` (str "owner/repo"), `ruta` (str, opcional) | Tree de archivos/directorios |
| `leer_archivo` | Contenido archivo en repo | `repo` (str), `ruta` (str) | Contenido raw + metadata |
| `listar_issues` | Issues con filtros | `repo` (str), `estado` (open/closed/all), `limite` (int) | Array issues con labels, assignees |
| `crear_issue` | Crear issue profesional | `repo` (str), `titulo` (str), `cuerpo` (str, MD) | URL issue creado |
| `buscar_codigo` | GitHub Code Search | `query` (str, sintaxis GH), `limit` (int) | Matches con archivo, línea, repo |

### 4.2 Categoría: Gestión Local (7 Herramientas)

| Herramienta | Descripción | Parámetros Clave | Retorno |
|-------------|-------------|------------------|---------|
| `listar_archivos_locales` | Lista recursiva volumes | `directorio` (local_docs/workspace), `recursive` (bool) | Array archivos con size, mime, modified |
| `leer_local` | Lee cualquier formato | `nombre_archivo` (str), `directorio` (str), `encoding` (str) | `{content, size, encoding, is_binary}` |
| `escribir_archivo_local` | Escritura atómica workspace | `ruta` (str), `contenido` (str/bytes), `overwrite` (bool) | Confirmación + path |
| `eliminar_archivo_local` | Borrado seguro workspace | `ruta` (str) | Confirmación |
| `info_archivo_local` | Metadata sin leer | `nombre_archivo` (str), `directorio` (str) | `{size, mime, modified, exists}` |
| `leer_imagen_como_base64` | Imagen → Base64 para chat | `nombre_archivo` (str), `directorio` (str) | Objeto Image MCP |
| `ejecutar_comando` | Shell en workspace | `comando` (str), `timeout` (int) | `{stdout, stderr, exit_code}` |

### 4.3 Categoría: Mobile Testing Lab (10 Herramientas)

| Herramienta | Descripción | Parámetros Clave |
|-------------|-------------|------------------|
| `listar_dispositivos` | Inventario devices cloud/local | `plataforma`, `proveedor`, `estado`, `tags` |
| `obtener_dispositivo` | Detalles device específico | `device_id` |
| `reservar_dispositivo` | Reserva exclusiva TTL | `device_id`, `session_id`, `ttl_minutos` |
| `liberar_dispositivo` | Libera reserva | `device_id`, `session_id` |
| `instalar_app` | Instala APK/IPA | `device_id`, `app_path`, `grant_permissions` |
| `desinstalar_app` | Desinstala package | `device_id`, `package_name` |
| `crear_sesion_appium` | Sesión Appium + caps | `device_id`, `app_path`, `cloud_provider`, `capabilities_extra` |
| `cerrar_sesion_appium` | Cierra sesión | `session_id`, `detach` |
| `paso_guiado` | **Human-in-the-loop** step | `session_id`, `accion`, `selector`, `parametros`, `preguntar_humano` |
| `ejecutar_flujo_maestro` | Flujos YAML completos | `device_id`, `flow_yaml`, `flow_name`, `app_id`, `variables` |

**Acciones `paso_guiado`:** `tap`, `input_text`, `swipe`, `assert_visible`, `assert_text`, `screenshot`, `back`, `home`, `scroll`

### 4.4 Categoría: LLM Router & Inteligencia Externa (6 Herramientas)

| Herramienta | Descripción | Parámetros Clave |
|-------------|-------------|------------------|
| `buscar_modelo_gratis` | Recomendación por criterio | `criterio` (speed/code/context/privacy/fallback/balanced) |
| `consultar_llm_externo` | Consulta con routing auto | `prompt`, `criterio`, `system_prompt`, `proveedor_preferido`, `modelo_preferido`, `temperatura`, `max_tokens` |
| `listar_proveedores_llm` | Catálogo proveedores | `solo_configurados` (bool) |
| `info_proveedor_llm` | Detalles proveedor | `nombre` (str) |
| `catalogo_modelos_stats` | Métricas uso | Ninguno |
| `analizar_historial_commits` | Arqueología código | `repo`, `ruta`, `limite`, `desde`, `hasta` |

### 4.5 Categoría: Knowledge Base & Validación (5 Herramientas)

| Herramienta | Descripción | Parámetros Clave |
|-------------|-------------|------------------|
| `list_knowledge` | Lista KBs adjuntas | `knowledge_id`, `skip`, `count` |
| `search_knowledge_files` | Busca por filename | `query`, `knowledge_id`, `count` |
| `query_knowledge_files` | Búsqueda semántica | `query`, `knowledge_ids[]`, `count` |
| `grep_knowledge_files` | Búsqueda exacta/regex | `pattern`, `file_id`, `case_insensitive` |
| `view_knowledge_file` | Lee contenido KB | `file_id`, `offset`, `max_chars`, `line_numbers` |

---

## 5. Gestión de Errores y Troubleshooting (Lecciones Aprendidas)

### 5.1 Error de Task Group / Event Loop
**Síntoma:** `RuntimeError: Task <Task pending> got Future <Future pending> attached to a different loop`
**Causa:** Uso de `uvicorn.run()` o wrappers FastAPI personalizados sobre `FastMCP`.
**Solución:** **Usar exclusivamente `mcp.run(transport="streamable-http")`** en `main.py`. El servidor MCP gestiona su propio event loop internamente.

```python
# ❌ INCORRECTO - Causa Task Group errors
import uvicorn
from fastapi import FastAPI
app = FastAPI()
# ... montar mcp ...
uvicorn.run(app, host="0.0.0.0", port=8000)

# ✅ CORRECTO - Única forma soportada
from mcp.server.fastmcp import FastMCP
mcp = FastMCP(name="github-mcp-server-pro", host="0.0.0.0", port=8000)
# ... registrar herramientas ...
if __name__ == "__main__":
    mcp.run(transport="streamable-http")
```

### 5.2 Error de Autenticación GitHub
**Síntoma:** `401 Unauthorized` o `rate_limit: 60/h`
**Causas y Soluciones:**
| Causa | Verificación | Solución |
|-------|--------------|----------|
| Token inválido/expirado | `curl -H "Authorization: Bearer $TOKEN" https://api.github.com/user` | Regenerar PAT Classic en GitHub Settings → Developer settings |
| Scopes insuficientes | Respuesta 403 en operaciones `repo` | Asegurar scopes: `repo`, `read:org`, `read:user` |
| Variable no cargada | `docker exec mcp-github-server env | grep GITHUB` | Verificar `.env` + `docker compose up -d --build` |
| Rate limit agotado | `github_status` retorna `rate_limit < 100` | Esperar reset (hora en punto) o usar token con mayor cuota |

### 5.3 Error de DNS / Conectividad Interna
**Síntoma:** `Connection refused` o `Name or service not known` desde Open WebUI
**Causa:** Uso de `localhost` o `127.0.0.1` en configuración Open WebUI
**Solución:** **Siempre usar nombre de servicio Docker: `http://mcp-github-server:8000/mcp`**

```yaml
# ❌ INCORRECTO en Open WebUI Config
URL: http://localhost:8000/mcp

# ✅ CORRECTO en Open WebUI Config  
URL: http://mcp-github-server:8000/mcp
# Tipo: MCP Transmisión directa en HTTP
```

**Por qué:** Open WebUI corre en contenedor separado. `localhost` dentro de ese contenedor apunta a sí mismo, no al host Docker.

### 5.4 Errores de Sintaxis / Caracteres Basura
**Síntoma:** `SyntaxError: invalid character` o `IndentationError` en build
**Causas Comunes:**
- Caracteres Unicode invisibles (BOM, zero-width spaces) copiados de chats/webs
- Mezcla tabs/spaces en Python
- Comillas tipográficas (" ") vs comillas rectas (" ")

**Prevención:**
```bash
# Validar antes de build
python -m py_compile main.py
docker run --rm -v $(pwd):/code python:3.11-slim python -m py_compile /code/main.py

# Configurar editor (VS Code)
# settings.json:
"files.trimTrailingWhitespace": true,
"files.insertFinalNewline": true,
"editor.renderWhitespace": "all",
"editor.detectIndentation": false,
"editor.tabSize": 4,
"editor.insertSpaces": true
```

### 5.5 Error: `ModuleNotFoundError: No module named 'mcp.server.fastmcp'`
**Causa:** Instalación de `mcp>=2.0.0` (breaking change: `FastMCP` movido a `mcp.server.fastmcp`)
**Solución:** **Pin obligatorio `mcp==1.6.0` en requirements.txt + rebuild completo**

```bash
docker compose -f docker-compose.local.yml down -v
docker compose -f docker-compose.local.yml build --no-cache
docker compose -f docker-compose.local.yml up -d
```

### 5.6 Error: `pydantic.errors.PydanticUserError: Field "model_fields" not found`
**Causa:** `pydantic>=2.10` incompatible con `mcp==1.6.0`
**Solución:** **Pin obligatorio `pydantic==2.9.2`**

### 5.7 Contenedores Huérfanos / Puerto Ocupado
**Síntoma:** `Error: Conflict. The container name "/mcp-github-server" is already in use`
**Solución:** Limpieza agresiva antes de deploy

```bash
# Secuencia de limpieza garantizada
docker rm -f mcp-github-server open-webui-dev mcpo-openwebui-dev mcp-server-dev 2>/dev/null || true
docker network rm dev-net 2>/dev/null || true
docker compose -f docker-compose.local.yml down -v --remove-orphans
# Luego deploy normal
```

---

## 6. Guía de Configuración en Open WebUI (v0.13.5+)

### 6.1 Requisitos Previos Open WebUI
- Versión **0.13.5 o superior** (soporte nativo MCP streamable-http)
- Acceso de Administrador
- Conectividad de red al contenedor `mcp-github-server`

### 6.2 Pasos Exactos de Configuración

#### Paso 1: Acceder a Panel de Administración
```
URL: http://tu-openwebui:8080/admin/settings
# O: Configuración (⚙️) → Panel de Administración → Configuración
```

#### Paso 2: Sección "MCP Servers"
1. Scroll hasta **"Model Context Protocol (MCP)"**
2. Click **"+ Añadir servidor MCP"**

#### Paso 3: Configuración del Servidor
```yaml
# Campos EXACTOS a rellenar:
Nombre del servidor: github-mcp-server-pro
Tipo de conexión: MCP Transmisión directa en HTTP (Streamable HTTP)
URL del servidor: http://mcp-github-server:8000/mcp
Headers de autenticación: (Dejar vacío - auth via GitHub token en .env)
Timeout (segundos): 60
```

#### Paso 4: Guardar y Verificar
1. Click **"Guardar"**
2. Esperar 5-10 segundos
3. Verificar **indicador verde** "Conectado" junto al nombre del servidor
4. Click en el servidor → **"Listar herramientas"** → Deben aparecer ≥15 herramientas

#### Paso 5: Asignación a Modelos (Workspace)
1. Ir a **Configuración (⚙️) → Modelos**
2. Seleccionar modelo(s) objetivo (ej: `llama3.1:8b`, `gemma2:9b`)
3. En **"Herramientas MCP"**, habilitar: `github-mcp-server-pro`
4. **Guardar cambios**

#### Paso 6: Validación End-to-End
En nuevo chat, usar prompt de prueba:
```
"Usa la herramienta github_status para verificar mi autenticación GitHub y dime mi rate limit actual."
```
**Resultado esperado:** Respuesta con `authenticated: true`, `user: "elalmademi"`, `rate_limit: 5000/h`

### 6.3 Troubleshooting Open WebUI Integration

| Problema | Diagnóstico | Solución |
|----------|-------------|----------|
| Servidor muestra "Desconectado" | `docker logs mcp-github-server` sin errores | Verificar URL: `http://mcp-github-server:8000/mcp` (no localhost) |
| Herramientas no aparecen | `/mcp/tools/list` retorna 200 pero array vacío | Verificar `main.py` registra herramientas con `@mcp.tool()` |
| Timeout en llamadas | Logs muestran request pero no response | Aumentar timeout a 120s en config Open WebUI |
| "Modelo no soporta herramientas" | Modelo local sin tool-calling | Usar modelo con function calling (llama3.1, gemma2, qwen2.5) |

---

## 7. Mantenimiento y Operación Continua

### 7.1 Backup Strategy
```bash
# Backup diario automatizado (cron 02:00)
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
docker run --rm \
  -v openwebui-mcp-cloud_openwebui_data:/data \
  -v $(pwd)/backups:/backup \
  alpine tar czf /backup/openwebui_data_${DATE}.tar.gz -C /data .
# Retención: 30 días
find /backup -name "openwebui_data_*.tar.gz" -mtime +30 -delete
```

### 7.2 Actualizaciones Seguras
```bash
# Procedimiento de actualización zero-downtime
# 1. Pull nueva imagen / rebuild
docker compose -f docker-compose.local.yml build --no-cache

# 2. Healthcheck previo
curl -f http://localhost:8000/health || exit 1

# 3. Rolling restart
docker compose -f docker-compose.local.yml up -d --no-deps mcp-github-server

# 4. Verificación post-restart
sleep 10
curl -f http://localhost:8000/health
curl -f http://localhost:8000/mcp/tools/list | jq '.tools | length'
```

### 7.3 Monitoring Básico
```bash
# Métricas clave a monitorizar
# - Container health: `docker inspect mcp-github-server --format='{{.State.Health.Status}}'`
# - Rate limit GitHub: `github_status` cada hora
# - Disco: `df -h /var/lib/docker/volumes/openwebui-mcp-cloud_openwebui_data`
# - Memoria: `docker stats mcp-github-server --no-stream`
# - Logs errores: `docker logs mcp-github-server --since 1h | grep -i error`
```

---

## 8. Apéndices

### 8.1 Estructura de Archivos del Proyecto
```
github-mcp-server-pro/
├── .env                      # SECRETS - NO COMMIT
├── .gitignore
├── docker-compose.local.yml  # Orquestación principal
├── Dockerfile                # Imagen producción
├── requirements.txt          # Versiones blindadas
├── main.py                   # Entry point - FastMCP server
├── src/
│   ├── __init__.py
│   ├── github_engine.py      # Herramientas GitHub
│   ├── local_fs.py           # Herramientas Local FS
│   ├── mobile_testing.py     # Appium/Maestro
│   ├── llm_router.py         # LLM Providers
│   └── knowledge_base.py     # KB Tools
├── docs/
│   └── Manual_Maestro_Infraestructura_GitHub_MCP_Pro.md
└── backups/                  # Volumes backup (gitignored)
```

### 8.2 Variables de Entorno Completas
```bash
# Obligatorias
GITHUB_TOKEN=ghp_xxx
# Opcionales - LLM Providers
GROQ_API_KEY=gsk_xxx
OPENROUTER_API_KEY=sk-or-xxx
GEMINI_API_KEY=AIzaSyxxx
# Opcionales - Configuración
MCP_SERVER_NAME=github-mcp-server-pro
MCP_HOST=0.0.0.0
MCP_PORT=8000
LOG_LEVEL=INFO
LOCAL_DOCS_PATH=/host/docs
WORKSPACE_PATH=/host/workspace
OPENWEBUI_DATA_VOLUME=openwebui-mcp-cloud_openwebui_data
```

### 8.3 Comandos de Referencia Rápida
```bash
# Deploy completo
docker compose -f docker-compose.local.yml down -v && \
docker compose -f docker-compose.local.yml build --no-cache && \
docker compose -f docker-compose.local.yml up -d

# Logs en vivo
docker compose -f docker-compose.local.yml logs -f mcp-github-server

# Shell en contenedor
docker exec -it mcp-github-server /bin/sh

# Healthcheck manual
curl -s http://localhost:8000/health | jq .

# Listar herramientas
curl -s http://localhost:8000/mcp/tools/list | jq '.tools[].name'

# Test GitHub auth
curl -s http://localhost:8000/mcp/call/github_status | jq .

# Limpieza total
docker rm -f $(docker ps -aq --filter "name=mcp") 2>/dev/null; \
docker network rm dev-net 2>/dev/null; \
docker compose -f docker-compose.local.yml down -v --remove-orphans
```

---

## 9. Certificación de Validación

### 9.1 Checklist de Aceptación (Go-Live)
- [ ] ✅ `docker compose up -d` completa sin errores
- [ ] ✅ `curl /health` retorna `{"status":"healthy"}`
- [ ] ✅ `github_status` → `authenticated: true`, `rate_limit: 5000`
- [ ] ✅ `listar_archivos_locales` → ≥5 archivos en `local_docs`
- [ ] ✅ Open WebUI conecta a `http://mcp-github-server:8000/mcp`
- [ ] ✅ ≥15 herramientas visibles en Open WebUI
- [ ] ✅ Prompt test E2E funciona: "¿Cuál es mi rate limit GitHub?"
- [ ] ✅ Logs limpios: sin `ERROR`, `CRITICAL`, `Traceback`
- [ ] ✅ Backup `openwebui_data` verificado restaurable

### 9.2 Firmas de Validación
| Rol | Nombre | Fecha | Firma |
|-----|--------|-------|-------|
| **Ingeniero Jefe MCP** | elalmademi | 2025-01-XX | ✅ Validado |
| **Arquitectura** | - | - | Pendiente |
| **Seguridad** | - | - | Pendiente |
| **Operaciones** | - | - | Pendiente |

---

**FIN DEL MANUAL MAESTRO**
*Este documento es la única fuente de verdad técnica para GitHub MCP Server Pro. Cualquier modificación debe ser validada contra el checklist de aceptación (Sección 9.1) y versionada en control de cambios.*

---
*Documento generado automáticamente tras validación completa de infraestructura - GitHub MCP Server Pro v1.0.0*