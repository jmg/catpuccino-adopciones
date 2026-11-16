"""Avisa a los candidatos de los animales adoptados que el animal ya tiene familia, y les
ofrece otros en adopción (services/aviso_candidatos.py).

No hace falta un cron propio: expirar_animales lo corre al final, todos los días. Esto es
para mirarlo o correrlo a mano. Sin --aplicar solo cuenta; nunca imprime nombres ni mails.
"""
from django.core.management.base import BaseCommand

from catus.services import aviso_candidatos


class Command(BaseCommand):

    help = "Avisa a los demás candidatos de los animales adoptados. Sin --aplicar solo cuenta."

    def add_arguments(self, parser):
        parser.add_argument("--aplicar", action="store_true", help="Manda los mails. Sin esto solo cuenta.")

    def handle(self, *args, **options):

        resultado = aviso_candidatos.avisar(aplicar=options["aplicar"])
        self.stdout.write(aviso_candidatos.resumen(resultado, options["aplicar"]))
