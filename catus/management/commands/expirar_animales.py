"""Saca del sitio los animales que llevan un mes publicados. Corre por cron, una vez por día.

Después de expirar le manda a cada rescatista un mail con los animales que le expiraron en
esa corrida, con botones para republicarlos o marcarlos adoptados (services/expiracion.py),
y al final manda los avisos "ya tiene familia" a los candidatos de los animales adoptados
(services/aviso_candidatos.py), para no necesitar otro cron. Que falle un mail no deshace ni
frena la expiración.

--avisar-ya-expirados --desde AAAA-MM-DD manda el mismo mail por los animales que ya estaban
expirados (los de antes de que existiera el mail). Sin --aplicar solo cuenta por rescatista.
"""
import logging
from datetime import datetime, time, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_date

from catus.models import Animal
from catus.services import aviso_candidatos, expiracion
from catus.signals import _update_form_field

logger = logging.getLogger(__name__)


class Command(BaseCommand):

    help = "Pasa a expirado a los animales en adopción publicados hace más de 30 días y avisa por mail."

    #Casi nadie marca la adopción en el sitio: en noviembre de 2026, 262 de los 309
    #animales publicados llevaban más de un mes, y 218 más de un año. Al mes de publicado
    #(o de republicado: fecha_ingreso) el animal sale del sitio, y el mail y el panel le
    #preguntan al rescatista si sigue en adopción; con un clic vuelve por otro mes.
    DIAS = expiracion.DIAS_PUBLICADO

    def add_arguments(self, parser):
        parser.add_argument("--simular", action="store_true", help="Dice cuántos expiraría y a cuántos avisaría, sin tocar nada.")
        parser.add_argument("--avisar-ya-expirados", action="store_true",
                            help="No expira: manda el mail por los animales ya expirados desde --desde.")
        parser.add_argument("--desde", help="AAAA-MM-DD, con --avisar-ya-expirados: los que expiraron desde ese día.")
        parser.add_argument("--aplicar", action="store_true", help="Con --avisar-ya-expirados: manda los mails. Sin esto solo cuenta.")

    def a_expirar(self, ahora):
        """Solo los que se ven en el sitio. Los reservados quedan: tienen a alguien en
        proceso y el panel ya pregunta por ellos."""

        return Animal.objects.filter(aprobado=True, estado="D", fecha_ingreso__lte=ahora - timedelta(days=self.DIAS))

    def handle(self, *args, **options):

        if options["avisar_ya_expirados"]:
            return self.avisar_ya_expirados(options["desde"], options["aplicar"])

        ahora = timezone.now()
        ids = list(self.a_expirar(ahora).values_list("id", flat=True))

        if options["simular"]:
            rescatistas = (self.a_expirar(ahora).filter(cargado_por__is_active=True).exclude(cargado_por__email="")
                           .exclude(cargado_por__email__isnull=True).values("cargado_por_id").distinct().count())
            self.stdout.write("expirar_animales (simulación): expirarían {} animales, con mail a {} rescatistas".format(
                len(ids), rescatistas))
            self.avisar_candidatos(aplicar=False)
            return

        if not ids:
            self.stdout.write("expirar_animales: nada para expirar")
        else:
            self.expirar(ids, ahora)

        self.avisar_candidatos(aplicar=True)

    def expirar(self, ids, ahora):

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

        #los de esta corrida: la base puede guardar la hora sin los microsegundos
        de_esta_corrida = expiracion.a_avisar().filter(id__in=ids, expiro_el__gte=ahora - timedelta(seconds=1))
        self.avisar_expirados(de_esta_corrida, aplicar=True)

    def avisar_expirados(self, animales, aplicar):
        """El mail a los rescatistas. Un error acá ya no puede deshacer la expiración, y no
        tiene que frenar el aviso a los candidatos."""

        try:
            resultado = expiracion.avisar(animales, aplicar=aplicar)
        except Exception as e:
            logger.warning("expirar_animales: no se pudieron mandar los avisos de expiración: %s", type(e).__name__)
            self.stdout.write("expirar_animales: no se pudieron mandar los avisos de expiración ({})".format(type(e).__name__))
            return None

        if resultado["local"] and aplicar:
            self.stdout.write("expirar_animales: en LOCAL no se mandan mails ({} rescatistas)".format(resultado["rescatistas"]))
        elif aplicar:
            self.stdout.write("expirar_animales: avisos de expiración: {} mails enviados, {} fallidos, {} sin intentar ({} animales)".format(
                resultado["enviados"], resultado["fallidos"], resultado["sin_intentar"], resultado["animales"]))

        return resultado

    def avisar_candidatos(self, aplicar):

        try:
            resultado = aviso_candidatos.avisar(aplicar=aplicar)
        except Exception as e:
            logger.warning("expirar_animales: no se pudieron mandar los avisos a los candidatos: %s", type(e).__name__)
            self.stdout.write("expirar_animales: no se pudieron mandar los avisos a los candidatos ({})".format(type(e).__name__))
            return

        self.stdout.write(aviso_candidatos.resumen(resultado, aplicar, prefijo="expirar_animales: avisos a candidatos"))

    def avisar_ya_expirados(self, desde, aplicar):

        fecha = parse_fecha(desde)
        animales = expiracion.a_avisar(desde=timezone.make_aware(datetime.combine(fecha, time.min)))

        resultado = expiracion.avisar(animales, aplicar=aplicar)

        #sin nombres ni mails: el id del rescatista alcanza para mirarlo en el admin
        if not aplicar or resultado["local"]:
            for rescatista_id, cantidad in resultado["por_rescatista"]:
                self.stdout.write("rescatista {}: {} animales".format(rescatista_id, cantidad))
            nota = "en LOCAL no se mandan mails" if aplicar else "simulación, sin --aplicar"
            self.stdout.write("expirar_animales --avisar-ya-expirados ({}): {} rescatistas, {} animales".format(
                nota, resultado["rescatistas"], resultado["animales"]))
            return

        self.stdout.write("expirar_animales --avisar-ya-expirados: {} mails enviados, {} fallidos, {} sin intentar ({} rescatistas, {} animales)".format(
            resultado["enviados"], resultado["fallidos"], resultado["sin_intentar"], resultado["rescatistas"], resultado["animales"]))


def parse_fecha(texto):
    """AAAA-MM-DD, o CommandError."""

    try:
        fecha = parse_date((texto or "").strip())
    except ValueError:
        fecha = None

    if fecha is None:
        raise CommandError("Falta --desde AAAA-MM-DD (por ejemplo --desde 2026-11-10).")

    return fecha
