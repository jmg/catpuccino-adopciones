import math
import re
from urllib.parse import urljoin, urlparse

import requests
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


INSTAGRAM_HOSTS = ("instagram.com", "www.instagram.com")

#los CDN que sirven las fotos de los posts de Instagram (scontent-*.cdninstagram.com,
#scontent-*.fbcdn.net): es de donde vienen las fotos que se importan de un post
INSTAGRAM_FOTO_DOMINIOS = ("cdninstagram.com", "fbcdn.net")

REDIRECTS = (301, 302, 303, 307, 308)


def _host_https(url):
    """El host de una URL https sin usuario ni contraseña, o None."""

    if not url or not isinstance(url, str):
        return None

    try:
        parsed = urlparse(url)
        host = parsed.hostname
    except ValueError:
        return None

    if parsed.scheme != "https" or parsed.username or parsed.password or not host:
        return None

    return host.lower().rstrip(".")


def es_url_de_instagram(url):
    """True si la URL es un link https de instagram.com.

    La pega el rescatista y el server la va a buscar: sin este chequeo se lo podía
    usar para pedir direcciones internas, que desde afuera no se ven.
    """

    return _host_https(url) in INSTAGRAM_HOSTS


def es_url_de_foto_de_instagram(url):
    """True si la URL es https y de un CDN de fotos de Instagram.

    Las URLs de las fotos las manda el navegador (instagram_image). urlopen() abría
    cualquier cosa, file:// incluido: el server leía sus propios archivos, como
    /proc/self/environ con los secretos de los tres sitios, y los guardaba como foto.
    """

    host = _host_https(url)

    return bool(host) and any(host == dominio or host.endswith("." + dominio) for dominio in INSTAGRAM_FOTO_DOMINIOS)


class DescargaRechazada(ValueError):
    pass


def descargar(url, es_permitida, max_bytes, timeout=20, max_redirects=3):
    """Baja una URL que pasa es_permitida, y lo mismo cada redirect, hasta max_bytes.

    requests sigue los redirects solo y el destino no vuelve a pasar por el filtro,
    así que se siguen a mano. timeout es por operación de red y además hay un tope
    total, para que una respuesta que gotea no tenga ocupado al worker.
    """

    limite = time.monotonic() + timeout * 2

    for _ in range(max_redirects + 1):

        if not es_permitida(url):
            raise DescargaRechazada("No se puede traer {}".format(url))

        response = requests.get(url, timeout=timeout, allow_redirects=False, stream=True)

        try:
            location = response.headers.get("Location")
            if response.status_code in REDIRECTS and location:
                url = urljoin(url, location)
                continue

            response.raise_for_status()

            try:
                declarado = int(response.headers.get("Content-Length") or 0)
            except ValueError:
                declarado = 0

            if declarado > max_bytes:
                raise DescargaRechazada("{} pesa demasiado".format(url))

            contenido = bytearray()
            for parte in response.iter_content(64 * 1024):
                contenido.extend(parte)
                if len(contenido) > max_bytes:
                    raise DescargaRechazada("{} pesa demasiado".format(url))
                if time.monotonic() > limite:
                    raise DescargaRechazada("{} tarda demasiado".format(url))

            return bytes(contenido)
        finally:
            response.close()

    raise DescargaRechazada("Demasiados redirects desde {}".format(url))
