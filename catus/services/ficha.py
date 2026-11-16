"""Lo que arma la página pública de cada animal (views/ficha.py) y lo que ven de ella los
buscadores y WhatsApp: el título, la descripción, la foto para compartir, el link al perfil
del rescatista. Son funciones puras salvo url_del_perfil, que consulta la base.
"""
import html
import re
from urllib.parse import quote

from django.utils.html import strip_tags

#lo que se le muestra a un buscador o a WhatsApp: más de ~160 caracteres lo cortan ellos
LARGO_DE_LA_DESCRIPCION = 160

#la descripción del animal la escribe cualquiera y puede ser larga: para un resumen
#alcanza con el principio, y strip_tags no tiene por qué recorrer 20.000 caracteres
LARGO_A_LEER = 3000

ESPECIE = {
    ("G", "M"): "gato", ("G", "H"): "gata", ("G", "A"): "gatos",
    ("P", "M"): "perro", ("P", "H"): "perra", ("P", "A"): "perros",
}


def especie(animal):
    """"gata", "perro", "gatos" (una camada, "Macho y Hembra")."""

    tipo = "P" if animal.tipo == "P" else "G"
    return ESPECIE.get((tipo, animal.sexo), "perro" if tipo == "P" else "gato")


def especie_en_plural(animal):

    return "perros" if animal.tipo == "P" else "gatos"


def es_plural(animal):
    """"Macho y Hembra" es una camada: "Tom y Jerry buscan familia"."""

    return animal.sexo == "A"


def terminacion(animal):
    """Para concordar: reservad-o, reservad-a, reservad-os."""

    if animal.sexo == "A":
        return "os"
    if animal.sexo == "H":
        return "a"
    return "o"


def texto_para_meta(valor, largo=LARGO_DE_LA_DESCRIPCION):
    """Texto enriquecido (HTML de un usuario) como una línea de texto plano, cortada en una
    palabra y con "…". El template lo vuelve a escapar al meterlo en el atributo."""

    texto = html.unescape(strip_tags((valor or "")[:LARGO_A_LEER]))
    texto = " ".join(texto.split())

    if len(texto) <= largo:
        return texto

    corte = texto[:largo - 1]
    if " " in corte:
        corte = corte.rsplit(" ", 1)[0]
    return corte.rstrip(" ,.;:") + "…"


def titulo_de_la_ficha(animal):
    """"Michi, gata en adopción en Lanús". Sin "en adopción" si ya no lo está."""

    if animal.estado != "D":
        return animal.nombre

    titulo = "{}, {} en adopción".format(animal.nombre, especie(animal))
    if animal.zona and animal.zona.strip():
        titulo += " en {}".format(animal.zona.strip())
    return titulo


def descripcion_de_la_ficha(animal):
    """La meta description: quién es y lo primero que cuenta su descripción."""

    if animal.estado != "D":
        return texto_para_meta("{} ya no {} en adopción. Mirá otros {} que buscan familia en Catpuccino Adopciones.".format(
            animal.nombre, "están" if es_plural(animal) else "está", especie_en_plural(animal),
        ))

    datos = [especie(animal)]
    if animal.edad and animal.edad.strip():
        datos.append(animal.edad.strip())
    if animal.zona and animal.zona.strip():
        datos.append("en {}".format(animal.zona.strip()))

    #"Michi busca familia: gata, 2 meses, en Lanús." Con comas y no con "de": la edad es
    #texto libre y "gata de bebés" no se lee bien
    cabeza = "{} {} familia: {}.".format(animal.nombre, "buscan" if es_plural(animal) else "busca", ", ".join(datos))
    return texto_para_meta("{} {}".format(cabeza, texto_para_meta(animal.datos, largo=LARGO_A_LEER)))


def imagen_para_compartir(fotos):
    """La foto que muestra WhatsApp al compartir el link: la del posteo de Instagram, que
    ya lleva el nombre y la edad, o si no la primera. Devuelve la URL relativa o None."""

    for foto in fotos:
        if foto.image_for_instagram:
            return foto.image_for_instagram.url

    for foto in fotos:
        if foto.image:
            return foto.image.url

    return None


def link_de_whatsapp(texto):
    """Abre WhatsApp con el mensaje escrito, para que la persona elija a quién mandarlo."""

    return "https://wa.me/?text={}".format(quote(texto, safe=""))


def url_del_perfil(usuario, handles_repetidos=None):
    """El perfil público del rescatista: /<handle>/ si es suyo, o /usuario/<id>/animales/.

    Quedaron cuentas que comparten handle (ver usuario.get_user_por_handle): /<handle>/
    muestra una sola, así que para las demás el link por id es el único que lleva a sus
    animales. Y un handle con caracteres que la URL no acepta daría 404. Quien arma muchos
    links (el sitemap) pasa los handles repetidos, en minúscula, para no consultar uno por uno.
    """
    from catus.models import CatusUser

    handle = usuario.handle or ""
    if not re.fullmatch(r"\w+", handle):
        return "/usuario/{}/animales/".format(usuario.id)

    if handles_repetidos is None:
        repetido = CatusUser.objects.filter(handle=handle).exclude(id=usuario.id).exists()
    else:
        repetido = handle.lower() in handles_repetidos

    if repetido:
        return "/usuario/{}/animales/".format(usuario.id)

    return "/{}/".format(handle)


def nombre_del_rescatista(usuario):
    """Cómo se llama quien publicó: el título de su perfil, su Instagram o su handle."""

    for nombre in (usuario.title, usuario.get_instagram(), usuario.handle):
        if nombre and nombre.strip():
            return nombre.strip()

    return None


def posicion_del_recorte(crop):
    """El object-position ("37.5% 50%") que deja a la vista el centro del recorte (x, y, w,
    h, fracciones de la foto) en un cuadro con object-fit: cover. None sin recorte.

    El recorte es cuadrado en píxeles, así que w * ancho == h * alto: la forma de la foto
    sale del propio recorte, sin leer el archivo. En una foto apaisada el cuadro muestra
    todo el alto y una franja del ancho (la fracción alto/ancho == w/h); en una vertical,
    al revés. object-position p% alinea el punto p% de la foto con el p% del cuadro, así
    que para que la franja visible empiece en `inicio` hace falta p = inicio / (1 - franja).
    """

    if crop is None:
        return None

    x, y, w, h = crop
    if w <= 0 or h <= 0:
        return None

    alto_sobre_ancho = w / h

    def porcentaje(centro, franja):
        if franja >= 0.999:
            return 50.0
        inicio = centro - franja / 2
        return min(max(inicio / (1 - franja), 0.0), 1.0) * 100

    if abs(alto_sobre_ancho - 1) < 0.01:
        return None

    if alto_sobre_ancho < 1:
        horizontal, vertical = porcentaje(x + w / 2, alto_sobre_ancho), 50.0
    else:
        horizontal, vertical = 50.0, porcentaje(y + h / 2, 1 / alto_sobre_ancho)

    #con punto y no con coma: es CSS, y el template no lo pasa por la localización
    return "{:.1f}% {:.1f}%".format(horizontal, vertical)


def descripcion_de_la_portada(gatos, perros):
    """La meta description de la portada: cuántos buscan familia hoy."""

    def cuantos(cantidad, singular, plural):
        return "{} {}".format(cantidad, singular if cantidad == 1 else plural)

    if gatos and perros:
        quienes = "{} y {} buscan".format(cuantos(gatos, "gato", "gatos"), cuantos(perros, "perro", "perros"))
    elif gatos or perros:
        cantidad = gatos or perros
        quienes = "{} {}".format(
            cuantos(cantidad, "gato", "gatos") if gatos else cuantos(cantidad, "perro", "perros"),
            "busca" if cantidad == 1 else "buscan",
        )
    else:
        return "Adopción responsable de gatos y perros: mirá los que buscan familia y completá el formulario de pre-adopción."

    return "{} familia. Mirá sus fotos, conocé su historia y completá el formulario de pre-adopción para adoptar de forma responsable.".format(quienes)
