"""Manda a BuenAdoptante lo pendiente: las solicitudes que no salieron en el momento
(BuenAdoptante no contestó al llegar el formulario) y las adopciones concretadas.

Si el reintento de una solicitud encuentra a la persona con 1★ o 2★, el formulario ya le
llegó al rescatista (BuenAdoptante no puede frenar un formulario por estar caído): no se
frena, se le avisa al rescatista y al equipo.

Corre cada 15 minutos. Manda pocos por corrida: el cupo de la API es diario.
"""
import html
import logging

from django.conf import settings
from django.core.management.base import BaseCommand

from catus.services.buenadoptante import CALIFICACIONES, BuenAdoptanteService
from catus.utils import send_html_email

logger = logging.getLogger(__name__)


class Command(BaseCommand):

    help = "Manda a BuenAdoptante las solicitudes y adopciones pendientes."

    POR_CORRIDA = 20

    def handle(self, *args, **options):

        servicio = BuenAdoptanteService()
        if not servicio.activo():
            self.stdout.write("BuenAdoptante está apagado: no se manda nada.")
            return

        enviadas = fallidas = avisos = 0
        for actividad in servicio.pendientes(self.POR_CORRIDA):
            if servicio.enviar(actividad):
                enviadas += 1
                if self.hay_que_avisar(actividad):
                    self.avisar(actividad)
                    actividad.avisado = True
                    actividad.save(update_fields=["avisado"])
                    avisos += 1
                elif servicio.avisar_coincidencia(actividad):
                    avisos += 1
            else:
                fallidas += 1

        self.stdout.write("BuenAdoptante: {} enviadas, {} sin enviar, {} avisos.".format(enviadas, fallidas, avisos))

    def hay_que_avisar(self, actividad):

        estado_form = actividad.estado_formulario
        return (actividad.tipo == "adoption_request" and actividad.bloqueo and not actividad.avisado
                and estado_form is not None and estado_form.estado != "B")

    def avisar(self, actividad):

        estado_form = actividad.estado_formulario
        animal = estado_form.gato
        nombre = animal.nombre if animal else "un animal"
        calificacion = CALIFICACIONES.get(actividad.nivel, "sin dato")

        subject = "Ojo con un candidato para {}: BuenAdoptante lo califica {}".format(nombre, calificacion)
        content = (
            "<p>La persona de un formulario de pre-adopción para <b>{animal}</b> figura en BuenAdoptante "
            "con calificación <b>{calificacion}</b>. BuenAdoptante no recomienda entregarle animales.</p>"
            "<p>El formulario te llegó antes de que BuenAdoptante contestara. Miralo antes de avanzar:<br>"
            "<a href='https://{host}/formularios/{hash}/'>https://{host}/formularios/{hash}/</a></p>"
        ).format(animal=html.escape(nombre), calificacion=calificacion, host=settings.HOST, hash=estado_form.hash)

        destinatarios = [settings.SEND_MAIL]
        if animal is not None and animal.cargado_por is not None and animal.cargado_por.email:
            destinatarios.append(animal.cargado_por.email)
        #y a quien sigue las coincidencias: para este formulario no sale otro aviso
        destinatarios = BuenAdoptanteService().destinatarios_coincidencias(ademas=destinatarios)

        try:
            send_html_email(subject, content, settings.SEND_MAIL, list(set(destinatarios)))
        except Exception as e:
            logger.warning("No se pudo avisar del candidato mal calificado del formulario %s: %s", estado_form.id, type(e).__name__)
