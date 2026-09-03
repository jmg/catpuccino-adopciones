"""Limpia el HTML que escriben los usuarios antes de mostrarlo.

La descripción del animal y la del perfil se editan con texto enriquecido, así que
tienen que poder llevar negritas, listas y links. Pero las escribe cualquiera que se
registre (el registro es abierto) y se muestran en páginas públicas, así que no se
pueden imprimir tal cual: se deja pasar una lista corta de etiquetas y se descarta
todo lo demás, incluidos los atributos on* y los href con javascript:.

No usamos una librería porque el deploy es un git pull sin pip install: una
dependencia nueva rompería el sitio en el próximo despliegue.
"""
import re

from html import escape
from html.parser import HTMLParser


#etiqueta -> atributos que se le permiten
TAGS_PERMITIDOS = {
    "p": (),
    "br": (),
    "b": (),
    "strong": (),
    "i": (),
    "em": (),
    "u": (),
    "s": (),
    "sub": (),
    "sup": (),
    "ul": (),
    "ol": (),
    "li": (),
    "h3": (),
    "h4": (),
    "h5": (),
    "h6": (),
    "blockquote": (),
    "hr": (),
    "a": ("href", "title"),
}

#no se cierran, así que no hay que llevarles la cuenta
TAGS_SIN_CIERRE = {"br", "hr"}

#de estas no alcanza con sacar la etiqueta: su contenido tampoco es texto para
#mostrar, así que se descarta entero (si no, el cuerpo del script queda a la vista)
TAGS_CON_CONTENIDO_DESCARTADO = {"script", "style", "noscript", "iframe", "object", "embed", "template"}

ESQUEMAS_PERMITIDOS = ("http", "https", "mailto")

#los navegadores ignoran espacios y caracteres de control adentro del esquema, así que
#"java\tscript:alert(1)" se ejecuta igual. Los sacamos nosotros: delegarlo en urlparse
#depende de hardenings de CPython (bpo-43882, CVE-2023-24329) que el Python viejo de
#producción puede no tener, y ahí se colaba un XSS almacenado.
_CONTROLES = re.compile(r"[\x00-\x20\x7f]")


def _esquema_de(valor):
    """El esquema tal como lo lee un navegador, sin depender de urlparse."""

    for i, caracter in enumerate(valor):
        if caracter == ":":
            return valor[:i].lower()
        if caracter in "/?#":
            #apareció un separador de ruta antes que los dos puntos: es relativo
            return ""

    return ""


def _href_seguro(valor):
    """Deja pasar solo links normales: nada de javascript: ni data:."""

    if not valor:
        return None

    limpio = _CONTROLES.sub("", valor)
    if not limpio:
        return None

    esquema = _esquema_de(limpio)

    if esquema and esquema not in ESQUEMAS_PERMITIDOS:
        return None

    #devolvemos lo ya limpio, no el original: lo que se emite tiene que ser
    #exactamente lo que validamos
    return limpio


class _Limpiador(HTMLParser):

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.partes = []
        self.abiertas = []
        self.descartando = 0

    def handle_starttag(self, tag, attrs):

        tag = tag.lower()

        if tag in TAGS_CON_CONTENIDO_DESCARTADO:
            self.descartando += 1
            return

        if tag not in TAGS_PERMITIDOS:
            #se descarta la etiqueta, pero el texto de adentro se conserva
            return

        permitidos = TAGS_PERMITIDOS[tag]
        atributos = ""

        for nombre, valor in attrs:
            nombre = (nombre or "").lower()
            if nombre not in permitidos:
                continue

            if nombre == "href":
                valor = _href_seguro(valor)
                if valor is None:
                    continue

            atributos += ' {}="{}"'.format(nombre, escape(valor or "", quote=True))

        if tag == "a" and 'href="' in atributos:
            #los links a otros sitios se abren aparte y sin pasar el referrer
            atributos += ' target="_blank" rel="noopener noreferrer nofollow"'

        if tag in TAGS_SIN_CIERRE:
            self.partes.append("<{}{}>".format(tag, atributos))
            return

        self.partes.append("<{}{}>".format(tag, atributos))
        self.abiertas.append(tag)

    def handle_startendtag(self, tag, attrs):

        if tag.lower() in TAGS_PERMITIDOS:
            self.handle_starttag(tag, attrs)
            if tag.lower() not in TAGS_SIN_CIERRE:
                self.handle_endtag(tag)

    def handle_endtag(self, tag):

        tag = tag.lower()

        if tag in TAGS_CON_CONTENIDO_DESCARTADO:
            self.descartando = max(0, self.descartando - 1)
            return

        if tag in TAGS_SIN_CIERRE or tag not in TAGS_PERMITIDOS:
            return

        if tag not in self.abiertas:
            return

        #cierra también lo que haya quedado abierto adentro
        while self.abiertas:
            abierta = self.abiertas.pop()
            self.partes.append("</{}>".format(abierta))
            if abierta == tag:
                break

    def handle_data(self, data):

        if self.descartando:
            return

        self.partes.append(escape(data, quote=False))

    def resultado(self):

        while self.abiertas:
            self.partes.append("</{}>".format(self.abiertas.pop()))

        return "".join(self.partes)


def sanitizar_html(valor):
    """Devuelve el HTML sin nada que pueda ejecutarse."""

    if not valor:
        return ""

    limpiador = _Limpiador()

    try:
        limpiador.feed(str(valor))
        limpiador.close()
    except Exception:
        #ante cualquier cosa rara preferimos texto plano antes que dejar pasar HTML
        return escape(str(valor), quote=False)

    return limpiador.resultado()
