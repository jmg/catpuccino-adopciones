#!/bin/bash

# Herramientas de desarrollo para Catpuccino Adopciones
# ./dev_tools.sh [comando]

VENV_PATH="/home/jm/Envs/catus"

# Colores
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Activar entorno virtual
. "$VENV_PATH/bin/activate"

show_help() {
    echo -e "${BLUE}🛠️  Herramientas de desarrollo - Catpuccino Adopciones${NC}"
    echo ""
    echo "Uso: ./dev_tools.sh [comando]"
    echo ""
    echo "Comandos disponibles:"
    echo -e "  ${GREEN}shell${NC}           - Abrir shell de Django"
    echo -e "  ${GREEN}migrate${NC}         - Aplicar migraciones"
    echo -e "  ${GREEN}makemigrations${NC}  - Crear migraciones"
    echo -e "  ${GREEN}createsuperuser${NC} - Crear superusuario"
    echo -e "  ${GREEN}collectstatic${NC}   - Recolectar archivos estáticos"
    echo -e "  ${GREEN}test${NC}            - Ejecutar tests"
    echo -e "  ${GREEN}check${NC}           - Verificar configuración"
    echo -e "  ${GREEN}clean${NC}           - Limpiar archivos .pyc y cache"
    echo -e "  ${GREEN}requirements${NC}    - Actualizar requirements.txt"
    echo -e "  ${GREEN}backup${NC}          - Hacer backup de la base de datos"
    echo -e "  ${GREEN}reset_db${NC}        - Resetear base de datos (¡CUIDADO!)"
    echo ""
}

case "$1" in
    "shell")
        echo -e "${YELLOW}🐍 Abriendo Django shell...${NC}"
        python manage.py shell
        ;;
    "migrate")
        echo -e "${YELLOW}🔄 Aplicando migraciones...${NC}"
        python manage.py migrate
        ;;
    "makemigrations")
        echo -e "${YELLOW}📝 Creando migraciones...${NC}"
        python manage.py makemigrations
        ;;
    "createsuperuser")
        echo -e "${YELLOW}👤 Creando superusuario...${NC}"
        python manage.py createsuperuser
        ;;
    "collectstatic")
        echo -e "${YELLOW}📦 Recolectando archivos estáticos...${NC}"
        python manage.py collectstatic --noinput
        ;;
    "test")
        echo -e "${YELLOW}🧪 Ejecutando tests...${NC}"
        python manage.py test
        ;;
    "check")
        echo -e "${YELLOW}🔍 Verificando configuración...${NC}"
        python manage.py check
        ;;
    "clean")
        echo -e "${YELLOW}🧹 Limpiando archivos temporales...${NC}"
        find . -name "*.pyc" -delete
        find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
        echo -e "${GREEN}✅ Limpieza completada${NC}"
        ;;
    "requirements")
        echo -e "${YELLOW}📋 Actualizando requirements.txt...${NC}"
        pip freeze > requirements.txt
        echo -e "${GREEN}✅ requirements.txt actualizado${NC}"
        ;;
    "backup")
        echo -e "${YELLOW}💾 Creando backup de la base de datos...${NC}"
        BACKUP_FILE="backup_$(date +%Y%m%d_%H%M%S).sqlite"
        cp catus.sqlite "$BACKUP_FILE"
        echo -e "${GREEN}✅ Backup creado: $BACKUP_FILE${NC}"
        ;;
    "reset_db")
        echo -e "${RED}⚠️  ADVERTENCIA: Esto eliminará TODOS los datos de la base de datos${NC}"
        echo -e "${YELLOW}¿Estás seguro? Escribe 'CONFIRMAR' para continuar:${NC}"
        read -r confirmation
        if [ "$confirmation" = "CONFIRMAR" ]; then
            echo -e "${YELLOW}🗑️  Eliminando base de datos...${NC}"
            rm -f catus.sqlite
            echo -e "${YELLOW}🔄 Ejecutando migraciones...${NC}"
            python manage.py migrate
            echo -e "${GREEN}✅ Base de datos reseteada${NC}"
        else
            echo -e "${BLUE}❌ Operación cancelada${NC}"
        fi
        ;;
    *)
        show_help
        ;;
esac