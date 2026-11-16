"""El backend de mail del sitio: la API v3 de SendGrid (POST /v3/mail/send) con requests.

Reemplaza a sendgrid-django 4.2.0 (sgbackend.SendGridBackend), sin mantenimiento y atado a
sendgrid 3.x. Arma el mismo pedido que armaba aquel con lo que usa el sitio
(utils.send_html_email, el reseteo de contraseña de Django): el texto y su versión HTML,
adjuntos (el contrato en PDF), reply_to, cc, bcc y el from con nombre.

Si SendGrid no acepta el mail, levanta SendGridError, como levantaba el backend viejo: los
que mandan ya lo esperan (send_html_email reintenta tres veces y después levanta, y las
vistas lo atrapan para no perder lo que ya se guardó). Con fail_silently no levanta, lo
loguea. El mensaje de error nunca lleva las direcciones: termina en Jentry.
"""
import base64
import logging
from email.mime.base import MIMEBase
from email.utils import parseaddr

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import EmailMultiAlternatives
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)

URL = "https://api.sendgrid.com/v3/mail/send"

#(conexión, respuesta). SendGrid contesta en menos de un segundo, y quien manda está
#esperando adentro de un pedido web: send_html_email reintenta tres veces
TIMEOUT = (5, 15)


class SendGridError(Exception):
    """SendGrid no aceptó el mail (status y lo que dijo, sin direcciones)."""


def direccion(texto):
    """{"email", "name"} de "Nombre <mail@dominio>" o de "mail@dominio"."""

    nombre, email = parseaddr(texto or "")
    resultado = {"email": email}
    if nombre:
        resultado["name"] = nombre
    return resultado


def _contenido_en_bytes(contenido):

    if isinstance(contenido, str):
        return contenido.encode("utf-8")
    return contenido


class SendGridBackend(BaseEmailBackend):

    def __init__(self, fail_silently=False, api_key=None, **kwargs):

        super().__init__(fail_silently=fail_silently, **kwargs)
        self.api_key = api_key or getattr(settings, "SENDGRID_API_KEY", None)

        #como el backend viejo: sin clave no hay con qué mandar, y es un error de config
        if not self.api_key:
            raise ImproperlyConfigured("Falta SENDGRID_API_KEY en la config para mandar mails.")

    def send_messages(self, email_messages):

        enviados = 0
        for mensaje in email_messages or []:
            try:
                self.enviar(mensaje)
            except (requests.RequestException, SendGridError) as error:
                if not self.fail_silently:
                    raise
                logger.warning("SendGrid no mandó el mail '%s': %s", mensaje.subject, error)
            else:
                enviados += 1

        return enviados

    def enviar(self, mensaje):

        respuesta = requests.post(
            URL, json=self.armar(mensaje), timeout=TIMEOUT,
            headers={"Authorization": "Bearer {}".format(self.api_key)},
        )

        #202 Accepted es lo normal; 200 lo devuelve el sandbox
        if respuesta.status_code not in (200, 202):
            raise SendGridError("SendGrid contestó {}: {}".format(respuesta.status_code, self.motivo(respuesta)))

    def motivo(self, respuesta):
        """Los "message" de los errores que manda SendGrid: dicen qué campo falló, sin las
        direcciones. Si no es el JSON de siempre, nada: el cuerpo podría traerlas."""

        try:
            errores = respuesta.json().get("errors") or []
            return "; ".join(str(e.get("message"))[:200] for e in errores if isinstance(e, dict)) or "sin detalle"
        except (ValueError, AttributeError):
            return "sin detalle"

    def armar(self, mensaje):
        """El JSON de /v3/mail/send para un EmailMessage de Django."""

        #SendGrid rechaza el mail entero si una dirección se repite entre to, cc y bcc
        vistas = set()

        def unicas(direcciones):
            resultado = []
            for texto in direcciones or []:
                datos = direccion(texto)
                clave = datos["email"].lower()
                if datos["email"] and clave not in vistas:
                    vistas.add(clave)
                    resultado.append(datos)
            return resultado

        personalizacion = {"to": unicas(mensaje.to), "subject": mensaje.subject}
        cc = unicas(mensaje.cc)
        if cc:
            personalizacion["cc"] = cc
        bcc = unicas(mensaje.bcc)
        if bcc:
            personalizacion["bcc"] = bcc

        #text/plain va primero (SendGrid lo exige) y no puede ir vacío
        contenido = [{"type": "text/plain", "value": mensaje.body or " "}]
        if isinstance(mensaje, EmailMultiAlternatives):
            for alternativa in mensaje.alternatives:
                html, tipo = alternativa[0], alternativa[1]
                if tipo == "text/html":
                    contenido.append({"type": "text/html", "value": html})
        elif mensaje.content_subtype == "html":
            contenido = [{"type": "text/plain", "value": " "}, {"type": "text/html", "value": mensaje.body}]

        datos = {
            "personalizations": [personalizacion],
            "from": direccion(mensaje.from_email),
            "subject": mensaje.subject,
            "content": contenido,
        }

        #SendGrid no acepta Reply-To como header: va aparte, y es una sola dirección. Si el
        #mensaje trae el header, gana sobre reply_to (como en el backend viejo).
        responder_a = None
        headers = {}
        for clave, valor in (mensaje.extra_headers or {}).items():
            if clave.lower() == "reply-to":
                responder_a = valor
            else:
                headers[clave] = str(valor)
        if headers:
            datos["headers"] = headers
        if responder_a is None and mensaje.reply_to:
            responder_a = mensaje.reply_to[0]
        if responder_a and direccion(responder_a)["email"]:
            datos["reply_to"] = direccion(responder_a)

        adjuntos = []
        for adjunto in mensaje.attachments:
            if isinstance(adjunto, MIMEBase):
                adjuntos.append({
                    "filename": adjunto.get_filename() or "adjunto",
                    "content": base64.b64encode(adjunto.get_payload(decode=True) or b"").decode("ascii"),
                    "type": adjunto.get_content_type(),
                })
            else:
                nombre, contenido_adjunto, tipo = adjunto[0], adjunto[1], adjunto[2]
                datos_adjunto = {
                    "filename": nombre,
                    "content": base64.b64encode(_contenido_en_bytes(contenido_adjunto)).decode("ascii"),
                }
                if tipo:
                    datos_adjunto["type"] = tipo
                adjuntos.append(datos_adjunto)
        if adjuntos:
            datos["attachments"] = adjuntos

        return datos
