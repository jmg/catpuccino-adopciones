"""Limpia las descripciones ya guardadas (animales y perfiles) con el mismo sanitizador
que usa |html_seguro.

Desde que AnimalForm.clean_datos y CatusUserForm.clean_description limpian al guardar, lo
nuevo entra limpio; esto es para lo que se guardó antes, que la pantalla de edición carga
en TinyMCE. Sin --aplicar solo cuenta; nunca imprime los textos.

    python manage.py sanear_textos            # cuántos cambiarían
    python manage.py sanear_textos --aplicar  # los limpia
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from catus.models import Animal, CatusUser
from catus.services.html_seguro import sanitizar_html


class Command(BaseCommand):
    help = "Limpia el HTML de las descripciones ya guardadas (Animal.datos, CatusUser.description)."

    def add_arguments(self, parser):
        parser.add_argument("--aplicar", action="store_true", help="guardar los cambios (sin esto, solo cuenta)")

    def handle(self, *args, **options):
        aplicar = options["aplicar"]
        for modelo, campo in ((Animal, "datos"), (CatusUser, "description")):
            revisados = cambiados = 0
            with transaction.atomic():
                for pk, valor in modelo.objects.exclude(**{campo: None}).exclude(**{campo: ""}).values_list("pk", campo).iterator():
                    revisados += 1
                    limpio = sanitizar_html(valor)
                    if limpio != valor:
                        cambiados += 1
                        if aplicar:
                            #update(): no dispara los signals de Animal ni toca updated_at
                            modelo.objects.filter(pk=pk).update(**{campo: limpio})
            self.stdout.write("{}.{}: {} revisados, {} {}".format(
                modelo.__name__, campo, revisados, cambiados, "limpiados" if aplicar else "cambiarían"))
