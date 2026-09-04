"""Agenda el posteo en Instagram cuando el animal se aprueba.

El pipeline era alta -> aprobado -> generar las imágenes a mano -> "marcar como listo"
a mano -> cron. Ahora aprobar deja el posteo agendado para dentro de un rato y el cron
lo saca cuando llega la hora.

Esa demora es lo único que separa una aprobación de un posteo en la cuenta de la
organización, así que es la ventana para cancelarlo: `aprobado=True` no garantiza que
alguien haya mirado la publicación, porque `automatic_approve` deja aprobando solos a
los rescatistas con historial.

Como ModeracionService, esto cuelga del alta y de la aprobación: pase lo que pase acá
adentro, el animal queda aprobado igual. Lo peor que puede pasar si esto falla es que
el equipo publique a mano desde /tools/, que es como se hacía siempre.
"""
import logging

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


class InstagramAutoService():

    #La ventana para cancelar el posteo. Ni tan corta que no llegue nadie a mirarlo, ni
    #tan larga que el rescatista no entienda por qué su animal no salió.
    DEMORA_MINUTOS = 30

    def esta_activo(self):

        valor = getattr(settings, "INSTAGRAM_AUTO_ACTIVO", False)

        #Apagado por defecto, y la ausencia de la clave cuenta como apagado. Postear en la
        #cuenta de la organización es irreversible y se ve de afuera: prenderlo tiene que
        #ser una decisión de alguien, no algo que empiece a pasar solo en el próximo
        #deploy. settings.py ya lee la clave con default False.
        if not self._es_verdadero(valor):
            return False

        #desde una máquina de desarrollo no se agenda nada que pueda terminar posteando
        #en la cuenta de la organización, igual que hacen MailService y ModeracionService
        return getattr(settings, "ENV", "LOCAL") != "LOCAL"

    def _es_verdadero(self, valor):
        """El flag puede llegar como bool o como el texto que deja read_config.

        read_config convierte todo el config a string, y en Python cualquier string no
        vacío es verdadero: sin esto, un "0" o un "false" en el JSON dejaban el posteo
        automático prendido y no había forma de apagarlo desde la config.

        None cuenta como apagado: para algo que postea en la cuenta de la organización,
        un valor que no sabemos leer tiene que dejarlo quieto y no publicando.
        """

        if valor is None:
            return False

        return str(valor).strip().lower() not in ("0", "false", "no", "")

    def get_demora(self):
        """Cuánto se espera entre aprobar y postear."""

        minutos = getattr(settings, "INSTAGRAM_AUTO_DEMORA_MINUTOS", None)

        try:
            minutos = int(minutos)
        except (TypeError, ValueError):
            #la clave puede no estar (None) o venir como texto del config: que alguien
            #escriba "media hora" ahí no puede tirar una excepción adentro de la
            #aprobación de un animal
            minutos = self.DEMORA_MINUTOS

        #agendar en el pasado es "publicá ya" para el cron, así que un cero o un negativo
        #borran la única ventana que tiene una persona para frenar el posteo
        if minutos <= 0:
            minutos = self.DEMORA_MINUTOS

        return timedelta(minutes=minutos)

    def agendar(self, animal):
        """Deja el posteo agendado. Devuelve True si lo agendó esta llamada.

        Idempotente a propósito: el link "Aprobar!" del mail se puede apretar dos veces
        y el admin guarda el mismo animal muchas veces. Volver a agendar correría la
        hora hacia adelante o resucitaría un posteo que el equipo ya canceló.
        """
        from catus.models import Animal

        try:
            if not self.esta_activo():
                return False

            if not self._se_puede_agendar(animal):
                return False

            programado = timezone.now() + self.get_demora()

            #se escribe con update() y no con save() a propósito: el post_save de Animal
            #reescribe el desplegable de forms_builder, y esto corre pegado a la
            #aprobación. El isnull es el candado contra dos aprobaciones a la vez.
            agendados = Animal.objects.filter(
                id=animal.id, instagram_programado_para__isnull=True,
            ).update(instagram_programado_para=programado)

            if not agendados:
                return False

            animal.instagram_programado_para = programado

            return True
        except Exception:
            #un fallo de esto no puede hacerle perder la aprobación a nadie: el animal ya
            #quedó aprobado y lo único que se pierde es el posteo automático, que el
            #equipo hace a mano desde /tools/ como siempre
            logger.exception("No se pudo agendar el posteo de %s", getattr(animal, "id", None))
            return False

    def cancelar(self, animal):
        """Saca al animal de la cola del posteo automático. True si había algo que sacar."""
        from catus.models import Animal

        try:
            if animal is None or animal.id is None:
                return False

            #ya salió: no hay posteo que cancelar y el post no vuelve solo
            if animal.instagram_publicado:
                return False

            #No alcanza con borrar la fecha: para el cron un animal listo y sin fecha es
            #uno del flujo viejo, o sea "publicá ya". Cancelando sólo la agenda, el
            #posteo salía en la corrida siguiente, que es justo lo que se cancelaba.
            #Se limpia también el motivo del último fallo: cancelar es justo el momento en
            #que ese motivo dejó de describir nada. Sin esto el animal cancelado quedaba
            #para siempre en el grupo "Con problemas" de /tools/colainstagram/, contando un
            #error de un posteo que ya no va a salir.
            Animal.objects.filter(id=animal.id).update(
                instagram_programado_para=None, instagram_listo_para_publicar=False,
                instagram_error=None,
            )

            animal.instagram_programado_para = None
            animal.instagram_listo_para_publicar = False
            animal.instagram_error = None

            return True
        except Exception:
            logger.exception("No se pudo cancelar el posteo de %s", getattr(animal, "id", None))
            return False

    def _se_puede_agendar(self, animal):
        from catus.models import Animal

        if animal is None or animal.id is None:
            return False

        #el posteo lo dispara la aprobación: sin aprobar no hay nada que agendar, y si
        #alguien lo desaprueba mientras tanto la agenda se cancela
        if not animal.aprobado:
            return False

        if animal.instagram_publicado:
            return False

        if animal.instagram_programado_para:
            return False

        #lo que la revisión automática marcó para mirar a mano no sale solo a la cuenta
        #de la organización. 'E' (no se pudo revisar) y 'P' (sin revisar) no son
        #sospecha: un fallo nuestro no se reporta como sospecha de la publicación ajena.
        if animal.revision_ia_estado == Animal.REVISION_REVISAR:
            return False

        return True
