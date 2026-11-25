FROM python:3.11-slim

# Evitar que Python genere archivos .pyc y asegurar logs en tiempo real
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# 1. Instalar dependencias del sistema (Java, Unzip, Curl)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    wget \
    ca-certificates \
    default-jre \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# 2. Crear usuario no root para seguridad
RUN groupadd -r appuser && useradd -r -g appuser -m -d /home/appuser -s /bin/bash appuser

# 3. Configurar directorio de trabajo
WORKDIR /home/appuser/app

# 4. Instalar dependencias de Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copiar el código del proyecto
COPY . .

# 6. Ajustar permisos para el usuario no root
RUN chown -R appuser:appuser /home/appuser/app

# 7. Cambiar al usuario no root
USER appuser

# Puerto donde corre el servidor
EXPOSE 8000

# Comando de arranque
CMD ["python", "main.py"]

