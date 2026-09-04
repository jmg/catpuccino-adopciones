"""Le da aprobación automática a los rescatistas con historial. Corre por cron."""
import logging

from django.core.management.base import BaseCommand

from catus.models import Animal, CatusUser

logger = logging.getLogger(__name__)


class Command(BaseCommand):

    help = "Marca automatic_approve en los rescatistas con suficientes animales aprobados."

    #Con un solo animal aprobado alcanzaba, así que a partir del segundo el rescatista se
    #auto-aprobaba solo. Mientras publicar en Instagram era a mano no se notaba; con el
    #posteo automático, aprobado=True agenda el posteo, y eso es publicar en la cuenta de
    #la organización sin que nadie haya mirado nunca más de una publicación suya.
    #Cinco aprobadas a mano son suficientes para conocer a alguien y siguen siendo pocas
    #semanas de uso: el que carga uno solo y prueba suerte no llega.
    MINIMO_APROBADOS = 5

    def handle(self, *args, **options):

        nuevos = 0
        revocados = 0

        #se miran TODOS, no sólo los que no la tienen. El mínimo se subió de 1 a 5, pero
        #el que ya tenía la marca la conservaba para siempre: como se otorgaba con un solo
        #animal aprobado, prácticamente todo el padrón viejo entraba. Subir el número sin
        #revisar a los que ya estaban adentro no cambiaba nada justo para los que importan.
        for user in CatusUser.objects.all():

            count = Animal.objects.filter(cargado_por=user, aprobado=True).count()
            corresponde = count >= self.MINIMO_APROBADOS

            if corresponde == user.automatic_approve:
                continue

            #esto era un print(): en un cron no lo lee nadie y no queda registro de por
            #qué un rescatista pasó a aprobación automática
            logger.info("%s tiene %s animales aprobados", user.get_instagram() or user.email, count)

            user.automatic_approve = corresponde
            user.save()

            if corresponde:
                nuevos += 1
                logger.info("%s pasa a aprobación automática", user.get_instagram() or user.email)
            else:
                revocados += 1
                #no es un castigo y se revierte solo: cuando llegue a MINIMO_APROBADOS
                #animales aprobados a mano, la corrida siguiente se la devuelve
                logger.info(
                    "%s vuelve a aprobación manual: tiene %s de los %s que hacen falta",
                    user.get_instagram() or user.email, count, self.MINIMO_APROBADOS,
                )

        self.stdout.write("Pasan a aprobación automática: {}. Vuelven a manual: {}.".format(
            nuevos, revocados,
        ))
