"""Los adoptados sin fecha de adopción: cuántos hay y, con --aplicar, ponérsela.

Elegir "Adoptado" en la edición del animal no ponía fecha de adopción (ahora pasa por
services/estados.py y sí): de 35 adopciones en 90 días, 15 quedaron sin fecha. Sin fecha el
panel no pregunta "¿Quién lo adoptó?", así que tampoco quedó el adoptante ni se mandó la
adopción a BuenAdoptante.

Sin --aplicar solo cuenta, por antigüedad de updated_at, que es lo más cerca que hay de
cuándo se marcó la adopción. Con --aplicar --desde AAAA-MM-DD les pone fecha_adopcion =
updated_at a los tocados desde ese día: el panel pregunta por los adoptados de los últimos
60 días (ProfileView.DIAS_ADOPTADOS_SIN_ADOPTANTE), y más atrás de eso la fecha no cambia
nada. Nunca imprime nombres ni mails.

Ojo con AVISO_CANDIDATOS_DESDE: un adoptado que queda con fecha posterior a ese corte hace
que sus candidatos reciban el aviso "ya tiene familia". Correr esto antes de configurar el
corte, o con --desde anterior al corte.
"""
from datetime import datetime, time, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db.models import F
from django.utils import timezone
from django.utils.dateparse import parse_date

from catus.models import Animal


class Command(BaseCommand):

    help = "Cuenta los adoptados sin fecha de adopción y, con --aplicar --desde, les pone la de updated_at."

    #(hasta cuántos días, etiqueta), de la más reciente a la más vieja
    TRAMOS = ((7, "última semana"), (30, "último mes"), (60, "últimos 60 días"), (90, "últimos 90 días"),
              (365, "último año"))

    def add_arguments(self, parser):
        parser.add_argument("--aplicar", action="store_true", help="Les pone la fecha. Necesita --desde.")
        parser.add_argument("--desde", help="AAAA-MM-DD: solo los adoptados con updated_at desde ese día.")

    def sin_fecha(self):

        return Animal.objects.filter(estado="A", fecha_adopcion__isnull=True)

    def handle(self, *args, **options):

        if options["aplicar"]:
            return self.aplicar(options["desde"])

        ahora = timezone.now()
        animales = self.sin_fecha()
        self.stdout.write("completar_fecha_adopcion: {} adoptados sin fecha de adopción".format(animales.count()))

        anterior = 0
        for dias, etiqueta in self.TRAMOS:
            hasta = animales.filter(updated_at__gte=ahora - timedelta(days=dias)).count()
            self.stdout.write("  tocados en {}: {} ({} en este tramo)".format(etiqueta, hasta, hasta - anterior))
            anterior = hasta

        self.stdout.write("  más de un año: {}".format(animales.filter(updated_at__lt=ahora - timedelta(days=365)).count()))
        self.stdout.write("  sin updated_at: {}".format(animales.filter(updated_at__isnull=True).count()))
        self.stdout.write("Para ponerles fecha: --aplicar --desde AAAA-MM-DD (la fecha queda = updated_at).")

    def aplicar(self, desde):

        try:
            fecha = parse_date((desde or "").strip())
        except ValueError:
            fecha = None
        if fecha is None:
            raise CommandError("--aplicar necesita --desde AAAA-MM-DD (por ejemplo --desde 2026-09-15).")

        corte = timezone.make_aware(datetime.combine(fecha, time.min))

        #un UPDATE: no cambia el estado, así que no hay desplegable que actualizar, y
        #updated_at queda como estaba, que es justamente la fecha que se copia
        completados = self.sin_fecha().filter(updated_at__gte=corte).update(fecha_adopcion=F("updated_at"))

        self.stdout.write("completar_fecha_adopcion: {} adoptados quedaron con fecha de adopción (tocados desde el {})".format(
            completados, fecha.strftime("%d/%m/%Y")))
