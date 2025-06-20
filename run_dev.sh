#!/bin/bash

# Script para ejecutar Catpuccino Adopciones en desarrollo
# ./run_dev.sh

set -e  # Salir si hay algún error

# Colores para output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Configuración
VENV_PATH="/home/jm/Envs/catus"
PROJECT_DIR="/home/jm/DESAROLLO/catpuccino-adopciones"
DJANGO_PORT=${DJANGO_PORT:-8000}

echo -e "${BLUE}🐱 Iniciando Catpuccino Adopciones...${NC}"

# Verificar que estamos en el directorio correcto
if [ ! -f "manage.py" ]; then
    echo -e "${RED}❌ Error: No se encontró manage.py. Asegúrate de estar en el directorio del proyecto.${NC}"
    exit 1
fi

# Verificar que existe el entorno virtual
if [ ! -d "$VENV_PATH" ]; then
    echo -e "${RED}❌ Error: No se encontró el entorno virtual en $VENV_PATH${NC}"
    exit 1
fi

echo -e "${YELLOW}📦 Activando entorno virtual...${NC}"
. "$VENV_PATH/bin/activate"

echo -e "${YELLOW}🔍 Verificando dependencias...${NC}"
# Verificar que Django esté instalado
if ! python -c "import django" 2>/dev/null; then
    echo -e "${RED}❌ Error: Django no está instalado en el entorno virtual${NC}"
    exit 1
fi

echo -e "${YELLOW}🔧 Verificando configuración de Django...${NC}"
python manage.py check

echo -e "${YELLOW}🗄️ Verificando migraciones...${NC}"
# Verificar si hay migraciones pendientes
if python manage.py showmigrations --plan | grep -q '\[ \]'; then
    echo -e "${YELLOW}⚠️  Hay migraciones pendientes. ¿Quieres aplicarlas? (y/N)${NC}"
    read -r response
    if [[ "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
        echo -e "${YELLOW}🔄 Aplicando migraciones...${NC}"
        python manage.py migrate
    fi
fi

echo -e "${YELLOW}👤 Verificando superusuario...${NC}"
# Verificar si existe al menos un superusuario
if ! python manage.py shell -c "from django.contrib.auth import get_user_model; User = get_user_model(); print('exists' if User.objects.filter(is_superuser=True).exists() else 'none')" | grep -q "exists"; then
    echo -e "${YELLOW}⚠️  No hay superusuarios. ¿Quieres crear uno? (y/N)${NC}"
    read -r response
    if [[ "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
        python manage.py createsuperuser
    fi
fi

echo -e "${YELLOW}🧹 Limpiando archivos .pyc...${NC}"
find . -name "*.pyc" -delete
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

echo -e "${GREEN}🚀 Iniciando servidor de desarrollo en puerto $DJANGO_PORT...${NC}"
echo -e "${BLUE}📱 Accede a: http://localhost:$DJANGO_PORT${NC}"
echo -e "${BLUE}🔧 Admin: http://localhost:$DJANGO_PORT/admin/${NC}"
echo -e "${YELLOW}💡 Presiona Ctrl+C para detener el servidor${NC}"
echo ""

# Iniciar el servidor de desarrollo
python manage.py runserver 0.0.0.0:$DJANGO_PORT