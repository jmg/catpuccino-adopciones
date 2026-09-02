import math
import re
from urllib.parse import urlparse

from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from django.utils import timezone
import time


def send_html_email(subject, content, from_email, to_email, fail_silently=False, bcc=None, cc=None, file=None, reply_to=None):

    if not isinstance(to_email, list):
        to_email = [to_email]

    if bcc is None:
        bcc = []
    if not isinstance(bcc, list):
        bcc = [bcc]

    if cc is None:
        cc = []
    if not isinstance(bcc, list):
        cc = [bcc]

    if reply_to is None:
        reply_to = to_email
    if not isinstance(reply_to, list):
        reply_to = [reply_to]

    msg = EmailMultiAlternatives(subject=subject, body=content, from_email=from_email, to=to_email, bcc=bcc, cc=cc, reply_to=reply_to)
    msg.attach_alternative(content, "text/html")

    if not isinstance(file, list):
        files = [file]
    else:
        files = file

    for file in files:
        if file:
            msg.attach(file["name"], file["content"], file["content_type"])

    error = None
    EMAIL_TRIES = 3

    for x in range(EMAIL_TRIES):
        try:
            return msg.send(fail_silently=fail_silently)
        except Exception as e:
            time.sleep(x+1)
            error = e

    raise error


INSTAGRAM_HOSTS = ("instagram.com", "www.instagram.com")


def es_url_de_instagram(url):
    """True si la URL es un link de instagram.com.

    La URL la pega el rescatista y el server la va a pedir, asi que no puede ser
    cualquier cosa: sin este chequeo se lo podia usar para alcanzar direcciones
    internas de la red que no son accesibles desde afuera.
    """

    if not url:
        return False

    try:
        parsed = urlparse(url)
    except ValueError:
        return False

    if parsed.scheme not in ("http", "https"):
        return False

    return parsed.hostname in INSTAGRAM_HOSTS


#hosts desde los que aceptamos traer una foto por URL. Son los CDN que sirven las
#imágenes de los posts de Instagram, que es de donde vienen.
IMAGEN_HOST_SUFIJOS = (
    ".cdninstagram.com",
    ".fbcdn.net",
    "instagram.com",
)


def es_url_de_imagen_publica(url):
    """True si la URL es una foto de Instagram que el server puede ir a buscar.

    urlopen() abre cualquier esquema, incluido file://, y cualquier host, incluidos
    los de la red interna. Como la URL la manda el navegador, sin este filtro se
    podía hacer que el server leyera archivos suyos y los guardara como foto.
    """

    if not url:
        return False

    try:
        parsed = urlparse(url)
    except ValueError:
        return False

    if parsed.scheme not in ("http", "https"):
        return False

    host = parsed.hostname or ""

    return any(
        host == sufijo or host.endswith(sufijo if sufijo.startswith(".") else "." + sufijo)
        for sufijo in IMAGEN_HOST_SUFIJOS
    )


def clean_crop(crop):
    """Valida un recorte (x, y, w, h) en fracciones de la foto original.

    Devuelve el recorte o None si no sirve. Las fracciones llegan del navegador,
    asi que no se puede confiar en que esten dentro de rango.
    """

    if crop is None:
        return None

    try:
        x, y, w, h = [float(value) for value in crop]
    except (TypeError, ValueError):
        return None

    #NaN pasa cualquier comparacion sin fallar, asi que hay que descartarlo aparte
    if not all(math.isfinite(value) for value in (x, y, w, h)):
        return None

    if w <= 0 or h <= 0:
        return None

    #un poco de tolerancia por los redondeos del selector
    if x < -0.001 or y < -0.001 or x + w > 1.001 or y + h > 1.001:
        return None

    return (max(0.0, x), max(0.0, y), min(1.0, w), min(1.0, h))


def parse_crop(data, suffix=""):
    """Lee el recorte de un POST (crop_x_<id>, crop_y_<id>, ...). None si no vino o es invalido."""

    try:
        crop = [data["crop_{}{}".format(key, suffix)] for key in ("x", "y", "w", "h")]
    except KeyError:
        return None

    return clean_crop(crop)


def has_crop_fields(data, suffix=""):
    """True si el form maneja el recorte, aunque venga vacio (vacio = volver al automatico)."""

    return "crop_x{}".format(suffix) in data


def get_context_columns(animals):

    if len(animals) == 1:
        cols = 12
    elif len(animals) == 2:
        cols = 6
    else:
        cols = 4

    return cols


def clean_html(raw_html):

    CLEANR = re.compile('<.*?>')
    cleantext = re.sub(CLEANR, '', raw_html)
    return cleantext


def rreplace(s, old, new, occurrence):
    li = s.rsplit(old, occurrence)
    return new.join(li)
