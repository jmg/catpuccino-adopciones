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

        nuevos = []

        #Solo se mira a los que no la tienen: este cron nunca la saca, así que lo que el
        #equipo tilda a mano en el admin queda. Lo contrario no: si el equipo se la saca
        #a alguien que tiene un animal aprobado por una persona, la corrida siguiente se
        #la vuelve a dar (es la regla de siempre). Para frenar a alguien hay que
        #desactivarle la cuenta.
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

            logger.info(
                "%s pasa a aprobación automática: tiene %s animales aprobados por una persona",
                user.get_instagram() or user.email, count,
            )

            #solo este campo: un save() entero pisaba con lo que había en memoria un cambio
            #de perfil hecho en el mismo momento. Y una fila con un problema no puede
            #cortar la corrida de todos los demás.
            try:
                user.automatic_approve = True
                user.save(update_fields=["automatic_approve"])
                nuevos.append(user.id)
            except Exception as error:
                logger.warning("No se pudo dar la aprobación automática al usuario %s: %s", user.id, type(error).__name__)

        #el logger.info de arriba no llega al log de producción (el nivel es WARNING): lo
        #que queda registrado del cron es esto, con los ids y sin datos personales
        ids = " (ids: {})".format(", ".join(str(i) for i in nuevos)) if nuevos else ""
        self.stdout.write("Pasan a aprobación automática: {}.{}".format(len(nuevos), ids))

        self.reintentar_revisiones()

    def reintentar_revisiones(self):
        """Lo que quedó en "no se pudo revisar" vuelve a pasar por la IA (services/revision_pendiente.py).

        Va en este cron porque ya corre cada hora y tiene su monitor en Jentry; un fallo acá no
        puede tapar lo de arriba, que ya se hizo.
        """
        from catus.services import revision_pendiente

        try:
            resumen = revision_pendiente.reintentar()
        except Exception as error:
            logger.warning("No se pudieron reintentar las revisiones: %s", type(error).__name__)
            return

        if resumen.get("apagada"):
            self.stdout.write("Revisiones pendientes: la revisión con IA está apagada.")
            return

        partes = ["{} {}".format(clave, valores) for clave, valores in resumen.items() if valores]
        self.stdout.write("Revisiones pendientes: {}.".format("; ".join(partes) if partes else "ninguna"))
