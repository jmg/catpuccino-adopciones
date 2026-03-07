#!/bin/bash

# Script rápido para ejecutar Catpuccino Adopciones
# ./start.sh [puerto]

DJANGO_PORT=${1:-8000}
VENV_PATH="/home/jm/Envs/catus"

echo "🐱 Iniciando Catpuccino Adopciones en puerto $DJANGO_PORT..."

# Verificar que existe el entorno virtual
if [ ! -f "$VENV_PATH/bin/activate" ]; then
    echo "❌ Error: No se encontró el entorno virtual en $VENV_PATH"
    exit 1
fi

# Activar entorno virtual
. "$VENV_PATH/bin/activate"

# Limpiar archivos compilados
find . -name "*.pyc" -delete 2>/dev/null || true

# Iniciar servidor
echo "🚀 Servidor disponible en: http://localhost:$DJANGO_PORT"
python manage.py runserver localhost:$DJANGO_PORT