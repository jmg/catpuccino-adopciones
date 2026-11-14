"""Saca del sitio los animales que llevan un mes publicados. Corre por cron, una vez por día."""
import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from catus.models import Animal
from catus.signals import _update_form_field

logger = logging.getLogger(__name__)


class Command(BaseCommand):

    help = "Pasa a expirado a los animales en adopción publicados hace más de 30 días."

    #Casi nadie marca la adopción en el sitio: en noviembre de 2026, 262 de los 309
    #animales publicados llevaban más de un mes, y 218 más de un año. Al mes de publicado
    #(o de republicado: fecha_ingreso) el animal sale del sitio, y el panel le pregunta al
    #rescatista si sigue en adopción; con un clic vuelve por otro mes.
    DIAS = 30

    def add_arguments(self, parser):
        parser.add_argument("--simular", action="store_true", help="Dice cuántos expiraría, sin tocar nada.")

    def a_expirar(self, ahora):
        """Solo los que se ven en el sitio. Los reservados quedan: tienen a alguien en
        proceso y el panel ya pregunta por ellos."""

        return Animal.objects.filter(aprobado=True, estado="D", fecha_ingreso__lte=ahora - timedelta(days=self.DIAS))

    def handle(self, *args, **options):

        ahora = timezone.now()
        ids = list(self.a_expirar(ahora).values_list("id", flat=True))

        if options["simular"]:
            self.stdout.write("expirar_animales (simulación): expirarían {} animales".format(len(ids)))
            return

        if not ids:
            self.stdout.write("expirar_animales: nada para expirar")
            return

        #Un UPDATE y no un save() por animal: cada save reescribe el desplegable de animales
        #del formulario público (signals), y la primera corrida trae cientos. El filtro por
        #estado se repite por si alguien lo cambió entre la consulta y esto. Se limpia la
        #agenda de Instagram: un animal que ya no está en el sitio no se postea.
        expirados = Animal.objects.filter(id__in=ids, aprobado=True, estado="D").update(
            estado="E", expiro_el=ahora, updated_at=ahora, pregunta_adopcion_hasta=None,
            instagram_listo_para_publicar=False, instagram_programado_para=None,
        )

        #el desplegable del formulario, una sola vez
        _update_form_field()

        #logger.info no llega al log de producción (el nivel es WARNING): lo que queda
        #registrado del cron es esto, con los ids y sin datos personales
        self.stdout.write("expirar_animales: {} animales expirados, ids {}".format(expirados, ids))
