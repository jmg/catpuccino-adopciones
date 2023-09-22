#!/bin/bash
HOST="root@adopciones.catpuccino.org"

ssh -T $HOST << ENDSSH
    cd /var/www/catpuccino-adopciones/
    git pull
    supervisorctl restart catpuccino_adopciones
ENDSSH