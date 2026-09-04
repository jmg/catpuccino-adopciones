#!/bin/bash
#
# Corre un comando de management con candado y con log. Lo usa el crontab (ver
# crontab.ejemplo); también sirve para dispararlos a mano en el servidor:
#
#     ./cron.sh publish
#
# POR QUÉ EL CANDADO
# Sin él, una corrida que se cuelga y la siguiente terminan trabajando sobre el mismo
# animal. En `publish` eso es un post duplicado en la cuenta de la organización, y un post
# no se deshace. El código ya tiene su propio candado por animal (un update atómico antes
# de tocar Graph, que cubre también el botón "Publicar" de /tools/), pero eso protege UN
# animal: éste protege la corrida entera y evita que se apilen procesos comiendo RAM.
#
# POR QUÉ SE LOGUEA EL SALTEO
# `flock -n` sale sin hacer nada y sin decir nada. Si una corrida queda colgada, las
# siguientes se saltean en silencio y el log simplemente se queda mudo: parece que no
# hubiera nada que hacer, cuando en realidad está todo trabado. El `-E 99` distingue "no
# pude tomar el candado" de "el comando falló", así que el salteo se puede anotar sin
# mentir cuando lo que falló fue el comando.

set -u

# --- ajustar en el servidor ---
# El path de acá es el de la máquina del autor. Para saber el del servidor:
#   supervisorctl status catpuccino_adopciones   y mirar el command
VENV="${CATUS_VENV:-/home/jm/Envs/catus}"
APP="${CATUS_APP:-/var/www/catpuccino-adopciones}"
LOGS="${CATUS_LOGS:-/var/log/catpuccino}"
export ENV="${ENV:-PRODUCTION}"
# ------------------------------

COMANDO="${1:-}"

if [ -z "$COMANDO" ]; then
    echo "Uso: $0 <comando de management>   (por ejemplo: $0 publish)" >&2
    exit 2
fi

if [ ! -x "$VENV/bin/python" ]; then
    echo "No existe el virtualenv en $VENV. Ajustá VENV en $0 o pasá CATUS_VENV." >&2
    exit 2
fi

mkdir -p "$LOGS"

LOG="$LOGS/$COMANDO.log"
LOCK="/var/lock/catus-$COMANDO.lock"

#si /var/lock no se puede escribir (no somos root), el candado va al lado de los logs
if ! : > "$LOCK" 2>/dev/null; then
    LOCK="$LOGS/catus-$COMANDO.lock"
fi

echo "$(date -Is) --- $COMANDO" >> "$LOG"

flock -n -E 99 "$LOCK" -c "cd '$APP' && '$VENV/bin/python' manage.py '$COMANDO'" >> "$LOG" 2>&1
SALIDA=$?

if [ "$SALIDA" -eq 99 ]; then
    echo "$(date -Is) salteada: ya hay una corrida de $COMANDO en curso" >> "$LOG"
    #no es un error: que se saltee es justamente lo que tiene que pasar
    exit 0
fi

if [ "$SALIDA" -ne 0 ]; then
    echo "$(date -Is) $COMANDO terminó con error $SALIDA" >> "$LOG"
fi

exit $SALIDA
