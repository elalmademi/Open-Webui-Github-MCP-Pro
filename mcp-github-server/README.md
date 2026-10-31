# 🚀 GitHub MCP Server Pro for Open WebUI

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009485.svg)](https://fastapi.tiangolo.com/)

Un servidor de **Model Context Protocol (MCP)** de grado profesional que transforma tu instancia de Open WebUI en un agente autónomo de ingeniería. Permite a la IA navegar repositorios, analizar el historial de desarrollo, procesar documentación técnica compleja y sincronizar datos locales con la nube en tiempo real.

---

## ✨ Capacidades del "Modo Dios"

A diferencia de los servidores MCP básicos, este sistema implementa flujos de trabajo cognitivos complejos:

- **📚 Omnilectura de Documentos**: Extracción de texto avanzada desde **PDFs**, **Word (.docx)** y archivos de texto plano, permitiendo que la IA analice manuales y contratos locales.
- **🏗️ Arquitecto de Repositorios**: Mapeo recursivo de la estructura de carpetas en GitHub para entender la arquitectura de cualquier proyecto sin necesidad de leer archivo por archivo.
- **🕰️ Arqueología de Código**: Análisis de la evolución del software mediante el estudio de commits, identificación de autores clave y detección de tendencias de desarrollo.
- **🌉 Puente de Sincronización (Local → Cloud)**: Capacidad de leer un documento local, analizar errores o mejoras y crear automáticamente Issues profesionales en GitHub tras verificar que no existan duplicados.

---

## 🛠️ Herramientas Disponibles

| Categoría | Herramienta | Capacidad Técnica |
|-----------|-------------|-------------------|
| **Local** | `listar_archivos_locales` | Escaneo de la carpeta `/app/local_docs` |
| | `leer_local` | Procesamiento de `.pdf`, `.docx`, `.txt`, `.md` |
| **GitHub** | `buscar_repo` | Búsqueda avanzada de repositorios y metadatos |
| | `mapear_repositorio` | Generación de árbol de directorios y estructura |
| | `leer_archivo` | Extracción de contenido de archivos remotos |
| | `analizar_historial_commits` | Análisis de evolución y autoría del código |
| | `buscar_issues_similares` | Detección de duplicados mediante keywords |
| | `listar_issues` | Auditoría de tickets abiertos/cerrados |
| | `crear_issue` | Escritura de tickets profesionales en la API |
| **Sistema** | `verificar_sistema` | Auto-diagnóstico de salud y dependencias |
| | `hola_mundo` | Verificación de conectividad básica |

---

## 📋 Requisitos Previos

- **Docker Desktop** (con WSL 2 habilitado en Windows).
- **GitHub Personal Access Token (PAT)** con scope `repo`.
- **Open WebUI** instalado y corriendo.
- **OpenRouter API Key** (o similar) configurada en Open WebUI.

---

## 🚀 Instalación y Despliegue

### 1. Clonar el repositorio

```bash
git clone https://github.com/TU_USUARIO/mcp-openwebui-server.git
cd mcp-openwebui-server
```

### 2. Configurar variables de entorno

Crea un archivo `.env` en la raíz del proyecto basándote en el ejemplo:

```bash
cp .env.example .env
```

Edita el `.env` con tu token:

```env
GITHUB_TOKEN=ghp_tu_token_aqui
```

### 3. Levantar la infraestructura

```bash
docker compose -f docker-compose.local.yml up -d --build
```

### 4. Conexión en Open WebUI

1. Ve a **Ajustes → Integraciones → Servidores de herramientas externas**.
2. Añade un nuevo servidor:
   - **Nombre**: GitHub MCP Pro
   - **URL**: `http://host.docker.internal:8888` (Windows/Mac) o `http://localhost:8888` (Linux)
3. Guarda y activa las herramientas en la configuración de tu modelo.

---

## ⚡️ Recetas de Poder (Prompts sugeridos)

### 🕵️ El Analista de Arquitectura

> "Mapea la estructura del repositorio [usuario/repo]. Analiza el árbol de carpetas, identifica dónde reside la lógica principal y lee el archivo más importante para explicarme cómo funciona la arquitectura."

### 🕰️ El Arqueólogo de Código

> "Analiza los últimos 30 commits de [usuario/repo]. ¿Quién es el autor más activo y cuál es la tendencia actual (corrección de bugs, nuevas features o refactorización)?"

### 🌉 El Puente de Sincronización (Local → GitHub)

> "Lee el archivo `reporte_errores.pdf` de mi carpeta local. Busca en el repo [usuario/repo] si ya existen issues similares. Si no existen, crea un issue detallado con la información del documento."

---

## 🛡️ Seguridad y Diseño

- **Aislamiento de Datos**: Los archivos locales se montan en modo Read-Only (`:ro`) para evitar modificaciones accidentales.
- **Protección de API**: Implementa un manejador de Rate Limits para evitar bloqueos de la API de GitHub.
- **Estabilidad**: Incluye un healthcheck avanzado que reinicia el servicio automáticamente en caso de congelamiento.

---

## 📄 Licencia

Este proyecto está bajo la licencia **MIT**. Libre para uso personal y comercial.

---

<p align="center">
  <strong>¡Potencia tu Open WebUI con capacidades de ingeniería autónoma! 🚀</strong>
</p>