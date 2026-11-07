"""Revisa todos los días el token con el que el sitio publica en Instagram.

Antes se guardaba el token del usuario, que vence a los 60 días, y este comando lo
renovaba. En enero de 2026 venció igual y la publicación quedó cortada diez meses sin
que nadie se enterara: el cron fallaba sin avisarle a nadie. Ahora se guarda el token de
la página, que no vence, y este comando:

- si encuentra un token de usuario (una cuenta conectada antes del cambio), lo cambia
  por el de la página;
- le pregunta a Facebook si el token sigue valiendo y cuándo se corta el acceso, y le
  hace una consulta de verdad a Instagram con él;
- si algo está por cortarse o ya se cortó, le manda un mail al equipo con el link para
  volver a conectar, y termina con error para que el cron quede en rojo.
"""
import logging
from datetime import datetime, timedelta, timezone as dt_timezone

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from catus.models import Animal, FacebookAccount
from catus.services.facebook import FacebookApiService
from catus.services.mail import MailService

logger = logging.getLogger(__name__)


class Command(BaseCommand):

    help = "Revisa el token de Instagram, lo pasa al de la página y avisa al equipo si hay que volver a conectar."

    #días de anticipación con que se avisa
    AVISAR_DIAS = 10

    def handle(self, *args, **options):

        account = FacebookAccount.objects.all().first()

        if account is None or not account.facebook_token:
            return self.avisar(["No hay ninguna cuenta de Instagram conectada."])

        try:
            info = FacebookApiService.debug_token(account.facebook_token)
        except Exception as e:
            #si no se le pudo preguntar a Facebook no se sabe nada del token: no es para
            #mandarle un mail al equipo, pero el cron queda en rojo
            raise CommandError("No se pudo revisar el token con Facebook: {}".format(e))

        if info.get("is_valid") and info.get("type") == "USER":
            info = self.pasar_al_token_de_la_pagina(account, info)

        self.stdout.write("Instagram: {} | token de {} | vence: {} | acceso a los datos hasta: {}".format(
            account.full_name, info.get("type"), self.fecha(info.get("expires_at")),
            self.fecha(info.get("data_access_expires_at")),
        ))

        problemas = self.problemas(account, info)

        if problemas:
            self.avisar(problemas)

    def pasar_al_token_de_la_pagina(self, account, info):

        try:
            token = FacebookApiService.get_page_token(account.facebook_token, account.remote_id)
            nuevo = FacebookApiService.debug_token(token)
        except Exception as e:
            logger.warning("No se pudo pasar al token de la página: %s", e)
            return info

        if not nuevo.get("is_valid"):
            return info

        account.facebook_token = token
        account.facebook_token_expire_at = None
        account.save()

        self.stdout.write("Se pasó al token de la página, que no vence.")

        return nuevo

    def problemas(self, account, info):

        if not info.get("is_valid"):
            motivo = (info.get("error") or {}).get("message") or "Facebook dice que ya no vale."
            return ["El token para publicar en Instagram dejó de andar: {}".format(motivo)]

        problemas = []
        limite = datetime.now(dt_timezone.utc) + timedelta(days=self.AVISAR_DIAS)

        #expires_at 0 es que no vence (el de la página)
        vence = info.get("expires_at")
        if vence and datetime.fromtimestamp(vence, dt_timezone.utc) < limite:
            problemas.append("El token para publicar en Instagram vence el {}.".format(self.fecha(vence)))

        #Facebook corta el acceso de la app si nadie la vuelve a autorizar en 90 días.
        #No está claro que eso frene publicar con el token de la página, pero volver a
        #conectar lleva un minuto y esperar a que se corte, días sin publicar.
        datos = info.get("data_access_expires_at")
        if datos and datetime.fromtimestamp(datos, dt_timezone.utc) < limite:
            problemas.append("Facebook corta el acceso del sitio el {} si nadie vuelve a conectar la cuenta (lo pide cada 90 días).".format(self.fecha(datos)))

        #lo que de verdad importa es que Instagram conteste con este token
        try:
            FacebookApiService.check_instagram(account)
        except Exception as e:
            problemas.append("Instagram no contesta con el token guardado: {}".format(e))

        return problemas

    def avisar(self, problemas):

        for problema in problemas:
            logger.error(problema)

        try:
            MailService().send_aviso_instagram(problemas, self.link_para_reconectar())
        except Exception:
            logger.exception("No se pudo mandar al equipo el aviso de Instagram")

        raise CommandError(" ".join(problemas))

    def link_para_reconectar(self):

        #el botón de Facebook está en la herramienta de imágenes, que es por animal
        animal_id = Animal.objects.order_by("-id").values_list("id", flat=True).first()

        return "{}/tools/generarimagen/{}/".format(settings.SSL_HOST, animal_id or 1)

    def fecha(self, timestamp):

        if timestamp == 0:
            return "no vence"

        if not timestamp:
            return "?"

        return datetime.fromtimestamp(timestamp, dt_timezone.utc).strftime("%d/%m/%Y")
