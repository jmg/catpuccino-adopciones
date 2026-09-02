"""Recomprime las fotos de la galería que quedaron pesadas.

Estaba roto de entrada: importaba save_image, que es un método de ImageService y
no una función del módulo; llamaba a Animal.get_images() sobre la clase en vez de
sobre cada animal; y leía image.imagen, un campo que no existe (es image).
"""
from django.core.management.base import BaseCommand

from catus.models import Animal
from catus.services.images import ImageService


class Command(BaseCommand):

    help = "Recomprime las fotos de los animales en adopción."

    def add_arguments(self, parser):

        parser.add_argument(
            "--max-width", type=int, default=1200,
            help="Lado más largo, en píxeles (por defecto 1200).",
        )
        parser.add_argument(
            "--todos", action="store_true",
            help="Procesa todos los animales, no solo los que están en adopción.",
        )

    def handle(self, *args, **options):

        animals = Animal.objects.all() if options["todos"] else Animal.get_all_for_adoption()

        service = ImageService()
        procesadas = 0
        fallidas = 0

        for animal in animals:
            for image in animal.get_images():

                if not image.image:
                    continue

                try:
                    service.optimize(image.image, max_width=options["max_width"])
                    procesadas += 1
                except Exception as error:
                    fallidas += 1
                    self.stderr.write("No se pudo optimizar la foto {} de {}: {}".format(
                        image.id, animal.nombre, error,
                    ))

        self.stdout.write("Fotos optimizadas: {}. Con error: {}.".format(procesadas, fallidas))
