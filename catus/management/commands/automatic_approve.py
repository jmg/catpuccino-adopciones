"""Le da aprobación automática a los rescatistas con historial. Corre por cron."""
import logging

from django.core.management.base import BaseCommand

from catus.models import Animal, CatusUser

logger = logging.getLogger(__name__)


class Command(BaseCommand):

    help = "Marca automatic_approve en los rescatistas con algún animal aprobado por una persona. Nunca la saca."

    #La regla de siempre, elegida de nuevo por el equipo el 7/11/2026: con un animal
    #aprobado por una persona alcanza. El merge de master la había subido a cinco y
    #revocaba a los que no llegaban: en la primera corrida le sacó la aprobación
    #automática a 329 rescatistas, y como corre cada hora deshacía en menos de una hora
    #el tilde que el equipo pusiera a mano en el admin.
    MINIMO_APROBADOS = 1

    def handle(self, *args, **options):

        nuevos = 0

        #Solo se mira a los que no la tienen: la marca nunca se saca acá. Sacarla es una
        #decisión del equipo (el tilde del admin), y este cron no la puede pisar.
        for user in CatusUser.objects.filter(automatic_approve=False):

            #Solo cuentan los que aprobó una PERSONA. Con la revisión automática prendida
            #la IA aprueba sola, y contar `aprobado=True` a secas dejaba fabricarse el
            #historial con un alta inocua que la IA dejara pasar. Con la revisión apagada
            #todo lo aprobado lo aprobó una persona, así que es la regla de siempre.
            count = Animal.objects.filter(
                cargado_por=user, aprobado=True, aprobado_por_persona=True,
            ).count()

            if count < self.MINIMO_APROBADOS:
                continue

            #esto era un print(): en un cron no lo lee nadie y no queda registro de por
            #qué un rescatista pasó a aprobación automática
            logger.info(
                "%s pasa a aprobación automática: tiene %s animales aprobados por una persona",
                user.get_instagram() or user.email, count,
            )

            user.automatic_approve = True
            user.save()
            nuevos += 1

        self.stdout.write("Pasan a aprobación automática: {}.".format(nuevos))
