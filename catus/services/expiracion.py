"""El mail "¿Siguen en adopción?" al rescatista cuando el cron le expira animales, y los
links de sus botones.

expirar_animales saca del sitio a todo animal que lleva un mes publicado, y la pregunta
"¿Siguen en adopción?" estaba solo en el panel, donde casi nadie entra: la primera semana
expiraron 254 animales, entraron 8 personas al panel y se republicaron unos 6. El mail lleva
la pregunta a donde está el rescatista: uno por rescatista y por corrida, con los animales
que le expiraron, y por cada uno dos botones, "Sigue en adopción" y "Ya se adoptó".

Los botones funcionan sin login. El link lleva un token firmado (django.core.signing, como
services/postulacion.py) con el id del animal, el de su rescatista y el momento en que
expiró: no se puede adivinar ni alterar, vence a los VIGENCIA_DIAS y deja de servir solo
cuando el animal cambia, porque republicarlo vacía expiro_el y una expiración nueva le pone
otro; también si el animal pasa a otra cuenta o la del rescatista se da de baja. Abre una
página (views/expirados.py) que con GET solo muestra, porque los escáneres de links de los
correos abren los GET, y con POST hace la acción con services/estados.py.

expiro_avisado_el marca a quién ya se le mandó el mail de esa expiración, así la corrida del
cron y el lote de los ya expirados (expirar_animales --avisar-ya-expirados) no mandan dos
veces el mismo aviso.
"""
import logging
from collections import namedtuple

from django.conf import settings
from django.core import signing
from django.db.models import F, Q
from django.template.loader import render_to_string
from django.utils import timezone

from catus.models import Animal
from catus.utils import send_html_email

logger = logging.getLogger(__name__)

SAL = "respuesta-animal-expirado"
VIGENCIA_DIAS = 30

#cuánto se ve un animal en el sitio desde que se publica (o se republica): lo que espera
#expirar_animales para sacarlo
DIAS_PUBLICADO = 30

#los demás se ven en el panel: un mail con cien animales no lo lee nadie, y Gmail corta
#los mails de más de ~100 KB
MAX_ANIMALES_POR_MAIL = 20

SIGUE = "sigue"
ADOPTADO = "adoptado"
RESPUESTAS = (SIGUE, ADOPTADO)

Link = namedtuple("Link", "animal vigente")


def _marca(expiro_el):
    """El momento de la expiración, en segundos: la base puede guardarlo con o sin los
    microsegundos y el token tiene que coincidir igual."""

    return int(expiro_el.timestamp())


def token(animal):

    return signing.dumps({"a": animal.id, "u": animal.cargado_por_id, "e": _marca(animal.expiro_el)}, salt=SAL)


def link(animal, respuesta=None):
    """La ruta del link para este animal, que tiene que estar expirado por el cron. Con
    `respuesta` la página muestra primero ese botón: es el que tocó en el mail."""

    ruta = "/sigue-en-adopcion/{}/".format(token(animal))
    if respuesta in RESPUESTAS:
        ruta += "?r={}".format(respuesta)

    return ruta


def leer(texto):
    """Link(animal, vigente), o None si el link no sirve: está mal escrito, venció, el
    animal ya no existe o es de otra cuenta, o la cuenta del rescatista está dada de baja.

    vigente es que el animal sigue expirado por esa misma expiración. Si no, ya se respondió
    (o lo cambiaron desde el panel) y la página dice cómo quedó, sin botones.
    """

    try:
        datos = signing.loads(texto or "", salt=SAL, max_age=VIGENCIA_DIAS * 24 * 60 * 60)
    except signing.BadSignature:
        #SignatureExpired también es BadSignature
        return None

    if not isinstance(datos, dict) or not isinstance(datos.get("a"), int):
        return None

    animal = Animal.objects.select_related("cargado_por").filter(id=datos["a"]).first()
    if animal is None or animal.cargado_por is None or animal.cargado_por_id != datos.get("u"):
        return None
    if not animal.cargado_por.is_active:
        return None

    vigente = animal.estado == "E" and animal.expiro_el is not None and _marca(animal.expiro_el) == datos.get("e")

    return Link(animal, vigente)


def a_avisar(desde=None):
    """Los animales que expiró el cron y cuyo rescatista todavía no recibió el mail de esa
    expiración. Solo de cuentas activas con mail, y no los que el rescatista ya contestó en
    el panel con "No republicar" o escondió por dos semanas (pregunta_adopcion_hasta), que
    es el mismo criterio de la tarjeta del panel."""

    ahora = timezone.now()

    animales = (Animal.objects
                .filter(estado="E", aprobado=True, expiro_el__isnull=False, cargado_por__is_active=True)
                .exclude(Q(cargado_por__email__isnull=True) | Q(cargado_por__email=""))
                .filter(Q(expiro_avisado_el__isnull=True) | Q(expiro_avisado_el__lt=F("expiro_el")))
                .filter(Q(pregunta_adopcion_hasta__isnull=True) | Q(pregunta_adopcion_hasta__lt=ahora)))

    if desde is not None:
        animales = animales.filter(expiro_el__gte=desde)

    return animales


def por_rescatista(animales):
    """[(rescatista, [animales])], los publicados más recientes primero: son los que más
    probablemente sigan en adopción."""

    grupos = {}
    for animal in animales.select_related("cargado_por").prefetch_related("animalimage_set").order_by("-fecha_ingreso", "id"):
        grupos.setdefault(animal.cargado_por_id, (animal.cargado_por, []))[1].append(animal)

    return sorted(grupos.values(), key=lambda grupo: grupo[0].id)


def avisar(animales, aplicar=True):
    """Manda un mail por rescatista con estos animales. Sin `aplicar` solo cuenta.

    Devuelve lo que pasó, en números: {"rescatistas", "animales", "enviados", "fallidos",
    "por_rescatista": [(id del rescatista, cantidad)], "local"}. Un mail que falla no
    corta a los demás ni a quien llama: se anota en el log como warning (Sentry adjunta los
    datos de la sesión a los ERROR) y ese animal queda sin marcar.
    """

    grupos = por_rescatista(animales)
    resultado = {
        "rescatistas": len(grupos),
        "animales": sum(len(lista) for _, lista in grupos),
        "enviados": 0,
        "fallidos": 0,
        "por_rescatista": [(rescatista.id, len(lista)) for rescatista, lista in grupos],
        #en LOCAL no sale nada: una copia de la base de producción tiene mails de verdad
        "local": settings.ENV == "LOCAL",
    }

    if not aplicar or resultado["local"]:
        return resultado

    for rescatista, lista in grupos:
        if mandar(rescatista, lista):
            resultado["enviados"] += 1
        else:
            resultado["fallidos"] += 1

    return resultado


def _primera_foto(animal):
    """La URL de la portada, con las fotos ya traídas (prefetch): el mismo orden que
    Animal.get_images, sin una consulta por animal."""

    fotos = sorted(animal.animalimage_set.all(), key=lambda foto: (foto.posicion is None, foto.posicion or 0, foto.id))
    for foto in fotos:
        if foto.image:
            return "{}{}".format(settings.SSL_HOST, foto.image.url)

    return None


def _nombre(animal):
    #el nombre lo escribe el rescatista y va en el asunto: un salto de línea ahí hace
    #que Django rechace el mail entero
    return " ".join((animal.nombre or "").split()) or "Tu animal"


def contenido(rescatista, animales):
    """(asunto, html) del mail."""

    en_el_mail = animales[:MAX_ANIMALES_POR_MAIL]

    for animal in en_el_mail:
        animal.foto_url = _primera_foto(animal)
        animal.link_sigue = settings.SSL_HOST + link(animal, SIGUE)
        animal.link_adoptado = settings.SSL_HOST + link(animal, ADOPTADO)

    if len(animales) == 1:
        asunto = "¿{} sigue en adopción?".format(_nombre(animales[0]))
    else:
        asunto = "¿Siguen en adopción? {} de tus animales dejaron de verse en el sitio".format(len(animales))

    html = render_to_string("email/expirados.html", {
        "animales": en_el_mail,
        "cantidad": len(animales),
        "resto": len(animales) - len(en_el_mail),
        "link_panel": "{}/accounts/profile/".format(settings.SSL_HOST),
        "settings": settings,
    })

    return asunto, html


def mandar(rescatista, animales):
    """Un mail a este rescatista con sus animales expirados. True si salió."""

    try:
        asunto, html = contenido(rescatista, animales)
        send_html_email(asunto, html, settings.SEND_MAIL, rescatista.email)
    except Exception as e:
        logger.warning("No se pudo mandar el aviso de expiración al rescatista %s: %s", rescatista.id, type(e).__name__)
        return False

    Animal.objects.filter(id__in=[animal.id for animal in animales]).update(expiro_avisado_el=timezone.now())
    return True
