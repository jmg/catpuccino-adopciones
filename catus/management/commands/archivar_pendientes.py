"""Marca como no publicados los animales que esperan aprobación hace demasiado.

No es un cron: se corre a mano, cuando el equipo decide vaciar la cola. Sin --aplicar sólo
cuenta, y ni así nombra a nadie: lo que imprime queda en el log de la corrida.

    python manage.py archivar_pendientes                      # cuántos, por antigüedad y cuenta
    python manage.py archivar_pendientes --dias 180 --aplicar --sin-mail   # el lote viejo
    python manage.py archivar_pendientes --aplicar            # más de 30 días, con mail
"""
import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from catus.services.pendientes import MOTIVO_SIN_REVISION, PendientesService

logger = logging.getLogger(__name__)


class Command(BaseCommand):

    help = "Marca como no publicados los animales que esperan aprobación hace más de N días."

    #En noviembre de 2026 había 58 animales sin aprobar, y 41 llevaban más de 180 días: la
    #cola estaba tapada y nadie la miraba. Lo que espera un mes ya no lo va a mirar nadie, y
    #a quien lo cargó le sirve más saberlo (con un mail que le dice cómo volver) que verlo
    #"En revisión" para siempre.
    DIAS = 30

    #Los cortes del resumen, en días: dicen cuánto de la cola es viejo de verdad.
    CORTES = (30, 90, 180, 365)

    def add_arguments(self, parser):
        parser.add_argument("--dias", type=int, default=self.DIAS,
                            help="Los que esperan hace más de estos días (por defecto {}).".format(self.DIAS))
        parser.add_argument("--aplicar", action="store_true",
                            help="Los marca. Sin esto sólo dice cuántos marcaría.")
        parser.add_argument("--sin-mail", action="store_true",
                            help="No le avisa a quien los cargó: para el lote viejo, que ya nadie espera.")

    def handle(self, *args, **options):

        dias = options["dias"]
        if dias < 1:
            self.stderr.write("archivar_pendientes: --dias tiene que ser 1 o más")
            return

        ahora = timezone.now()
        servicio = PendientesService()

        if not options["aplicar"]:
            self.resumen(servicio, dias, ahora)
            return

        archivados = servicio.archivar(dias, ahora)

        if not archivados:
            self.stdout.write("archivar_pendientes: nada para archivar con más de {} días".format(dias))
            return

        ids = [animal.id for animal in archivados]

        if options["sin_mail"]:
            avisados, sin_aviso = 0, 0
        else:
            avisados, sin_aviso = servicio.avisar(archivados, MOTIVO_SIN_REVISION)

        #logger.info no llega al log de producción (el nivel es WARNING): lo que queda
        #registrado es esto, con los ids y sin datos personales
        cuantos = len(archivados)
        self.stdout.write(
            "archivar_pendientes: {} {} como no publicado{} (más de {} días), ids {}. "
            "Mails: {} cuentas avisadas, {} sin aviso{}.".format(
                cuantos, "animal marcado" if cuantos == 1 else "animales marcados", "" if cuantos == 1 else "s",
                dias, ids, avisados, sin_aviso,
                " (--sin-mail)" if options["sin_mail"] else "",
            )
        )

    def resumen(self, servicio, dias, ahora):
        """Cuántos marcaría, por antigüedad y por cuenta (por id: ni nombres ni mails).

        Los que marcaría salen de la misma consulta que usa --aplicar, y no de una cuenta
        hecha acá: si no, la simulación y la corrida de verdad podían no coincidir.
        """

        filas = list(servicio.esperando().values_list("cargado_por_id", "esperando_desde"))
        a_archivar = list(servicio.esperando_hace_mas_de(dias, ahora).values_list("cargado_por_id", flat=True))

        self.stdout.write("archivar_pendientes (simulación): {} esperan aprobación; {} con más de {} días.".format(
            len(filas), len(a_archivar), dias,
        ))

        self.stdout.write("Por antigüedad (todos los que esperan):")
        for etiqueta, cuantos in self.por_antiguedad(filas, ahora):
            self.stdout.write("  {}: {}".format(etiqueta, cuantos))

        if not a_archivar:
            return

        por_cuenta = {}
        for cuenta in a_archivar:
            por_cuenta[cuenta] = por_cuenta.get(cuenta, 0) + 1

        self.stdout.write("Los que marcaría, por cuenta ({} cuentas):".format(len(por_cuenta)))
        for cuenta, cuantos in sorted(por_cuenta.items(), key=lambda fila: (-fila[1], fila[0] or 0)):
            self.stdout.write("  cuenta {}: {}".format(cuenta if cuenta is not None else "sin cuenta", cuantos))

        self.stdout.write("Para marcarlos: --aplicar (y --sin-mail para no avisar).")

    def por_antiguedad(self, filas, ahora):
        """[(etiqueta, cuántos)] por tramo de días esperando."""

        tramos = []
        desde = 0
        for corte in self.CORTES:
            tramos.append(("{} a {} días".format(desde, corte - 1) if desde else "menos de {} días".format(corte), desde, corte))
            desde = corte
        tramos.append(("{} días o más".format(desde), desde, None))

        cuentas = []
        for etiqueta, minimo, maximo in tramos:
            cuantos = sum(
                1 for _, esperando_desde in filas
                if esperando_desde is not None
                and (ahora - esperando_desde).days >= minimo
                and (maximo is None or (ahora - esperando_desde).days < maximo)
            )
            cuentas.append((etiqueta, cuantos))

        return cuentas
