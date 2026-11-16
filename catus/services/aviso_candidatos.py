"""El aviso "ya tiene familia" a los demás candidatos de un animal adoptado.

Quien manda el formulario de pre-adopción recibe la confirmación y después, si el rescatista
no lo elige, nada: en 90 días, 67 personas se postularon a animales que ya se adoptaron y
nunca supieron. Este aviso les cuenta que el animal encontró familia y les ofrece otros de
la misma especie, con el link para postularse con las mismas respuestas
(services/postulacion.py).

A quién: formularios de pre-adopción (A/AP) todavía abiertos ("No asignado" o "En proceso
de contacto") de animales adoptados. No a quien adoptó, ni a los frenados por BuenAdoptante,
los duplicados o los descartados, que no están en esos estados; tampoco al formulario
vinculado como el de quien adoptó, ni a una casilla que es la de quien adoptó. Igual el
texto es neutro ("si sos vos, ¡felicitaciones!"): a veces el rescatista no dice quién fue, o
la misma persona mandó dos formularios. El mail no dice nada de quien adoptó.

Cuándo: cuando ya se sabe quién adoptó, o a los DIAS_DE_ESPERA de la fecha de adopción,
para darle tiempo al rescatista a contestar "¿Quién lo adoptó?" en el panel. Y solo por
adopciones desde AVISO_CANDIDATOS_DESDE (settings): sin esa fecha no se avisa a nadie, así el
primer día no salen mails por adopciones de hace meses.

Un mail por casilla por corrida aunque se haya postulado a varios adoptados: se agrupa por
mail, y corre una vez por día, al final de expirar_animales. Ese mail cuenta para el tope
diario por casilla del mail de recibo (views/adoption.py, RECEIPTS_MAX_PER_DAY): la casilla
la escribió quien completó el formulario y nada prueba que sea suya. Si la casilla llegó al
tope, el aviso queda para el día siguiente.

aviso_cierre_el queda puesto en los avisados y en los que se saltean para siempre (mail
inválido, el de quien adoptó), así no se los vuelve a mirar. Un envío que falla queda sin
marcar y se reintenta en la próxima corrida.
"""
import hashlib
import logging
from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.dateparse import parse_date
from forms_builder.forms.models import Field, FieldEntry

from catus.models import Animal, EstadoFormulario
from catus.services import postulacion, throttle
from catus.services.buenadoptante import TIPOS_PREADOPCION
from catus.services.contacto import mail_valido
from catus.utils import send_html_email

logger = logging.getLogger(__name__)

#"No asignado" y "En proceso de contacto": los que siguen esperando una respuesta
ESTADOS_A_AVISAR = ("N", "P")
DIAS_DE_ESPERA = 3
MAX_SUGERIDOS = 4
#la primera corrida con un corte viejo no puede mandar cientos de mails de una: el resto
#sale en las corridas siguientes
MAX_CASILLAS_POR_CORRIDA = 200


def desde():
    """El corte (AVISO_CANDIDATOS_DESDE) como fecha y hora, o None: no se avisa a nadie."""

    valor = getattr(settings, "AVISO_CANDIDATOS_DESDE", None)
    if not valor:
        return None

    if isinstance(valor, datetime):
        corte = valor
    else:
        try:
            fecha = valor if isinstance(valor, date) else parse_date(str(valor).strip())
        except ValueError:
            fecha = None
        if fecha is None:
            logger.warning("AVISO_CANDIDATOS_DESDE no es una fecha AAAA-MM-DD: no se avisa a nadie")
            return None
        corte = datetime.combine(fecha, time.min)

    if timezone.is_naive(corte):
        corte = timezone.make_aware(corte)

    return corte


def pendientes(ahora=None):
    """Los formularios a los que ya les corresponde el aviso."""

    corte = desde()
    if corte is None:
        return EstadoFormulario.objects.none()

    ahora = ahora or timezone.now()

    return (EstadoFormulario.objects
            .filter(tipo__in=TIPOS_PREADOPCION, estado__in=ESTADOS_A_AVISAR, aviso_cierre_el__isnull=True,
                    gato__estado="A", gato__fecha_adopcion__gte=corte)
            .filter(Q(gato__estado_formulario__isnull=False)
                    | Q(gato__fecha_adopcion__lte=ahora - timedelta(days=DIAS_DE_ESPERA)))
            .select_related("gato", "copiado_de")
            .order_by("id"))


def mails(formularios):
    """{id del formulario: el mail que dejó, o None si no hay uno válido}. La respuesta
    "Email", como mail_del_adoptante (views/contrato.py), en dos consultas para todos."""

    entradas = {}
    for formulario in formularios:
        if formulario.form_entry_id:
            entradas.setdefault(formulario.form_entry_id, []).append(formulario.id)

    resultado = {f.id: None for f in formularios}
    if not entradas:
        return resultado

    campos = list(Field.objects.filter(label__iexact="Email").values_list("id", flat=True))
    respuestas = (FieldEntry.objects.filter(entry_id__in=list(entradas), field_id__in=campos)
                  .order_by("id").values_list("entry_id", "value"))

    #la primera respuesta válida de cada formulario
    for entry_id, valor in respuestas:
        for estado_id in entradas[entry_id]:
            if resultado[estado_id] is None:
                resultado[estado_id] = mail_valido(valor)

    return resultado


def por_casilla(formularios):
    """({casilla: (mail, [formularios])}, [salteados]). Se saltean, para siempre, los que no
    tienen un mail válido y los de quien adoptó."""

    adoptantes = EstadoFormulario.objects.filter(
        id__in={f.gato.estado_formulario_id for f in formularios if f.gato.estado_formulario_id})
    mail_de_quien_adopto = {}
    mails_adoptantes = mails(list(adoptantes))
    for adoptante in adoptantes:
        if mails_adoptantes.get(adoptante.id):
            mail_de_quien_adopto[adoptante.id] = mails_adoptantes[adoptante.id].lower()

    casillas, salteados = {}, []
    mails_formularios = mails(formularios)

    for formulario in formularios:
        mail = mails_formularios.get(formulario.id)
        adopto = formulario.gato.estado_formulario_id

        if not mail or formulario.id == adopto or mail.lower() == mail_de_quien_adopto.get(adopto):
            salteados.append(formulario)
            continue

        casillas.setdefault(mail.lower(), (mail, []))[1].append(formulario)

    return casillas, salteados


def marcar(formularios):

    EstadoFormulario.objects.filter(id__in=[f.id for f in formularios]).update(aviso_cierre_el=timezone.now())


def llego_al_tope(mail):
    """El tope diario por casilla del mail de recibo, que este aviso comparte."""
    #import acá: es una constante de la vista, y la vista no tiene por qué cargarse cuando
    #esto corre desde un comando
    from catus.views.adoption import RECEIPTS_MAX_PER_DAY

    casilla = hashlib.sha256(mail.lower().encode()).hexdigest()
    return throttle.hit("adoption-receipt", casilla, 24 * 60 * 60) > RECEIPTS_MAX_PER_DAY


def avisar(aplicar=True):
    """Manda los avisos que corresponden. Sin `aplicar` solo cuenta.

    Devuelve los números: {"formularios", "casillas", "salteados", "enviados", "fallidos",
    "topados", "para_despues", "local"}. Un envío que falla no corta a los demás: se anota
    como warning (Sentry adjunta los datos de la sesión a los ERROR) y se reintenta mañana.
    """

    formularios = list(pendientes())
    casillas, salteados = por_casilla(formularios)

    resultado = {
        "formularios": len(formularios),
        "casillas": len(casillas),
        "salteados": len(salteados),
        "enviados": 0,
        "fallidos": 0,
        "topados": 0,
        "para_despues": max(0, len(casillas) - MAX_CASILLAS_POR_CORRIDA),
        #en LOCAL no sale nada: una copia de la base de producción tiene mails de verdad
        "local": settings.ENV == "LOCAL",
    }

    if not aplicar or resultado["local"]:
        return resultado

    marcar(salteados)

    for mail, lista in list(casillas.values())[:MAX_CASILLAS_POR_CORRIDA]:

        if llego_al_tope(mail):
            resultado["topados"] += 1
            continue

        if mandar(mail, lista):
            marcar(lista)
            resultado["enviados"] += 1
        else:
            resultado["fallidos"] += 1

    return resultado


def resumen(resultado, aplicar, prefijo="avisar_candidatos"):
    """Una línea para la salida de los comandos, con números y nada más: ni nombres ni
    mails (queda en el log de producción)."""

    if desde() is None:
        return "{}: AVISO_CANDIDATOS_DESDE no está configurado, no se avisa a nadie".format(prefijo)

    if not aplicar or resultado["local"]:
        nota = "en LOCAL no se mandan mails" if aplicar else "simulación"
        return "{} ({}): {} formularios, {} casillas a avisar, {} sin mail válido o de quien adoptó".format(
            prefijo, nota, resultado["formularios"], resultado["casillas"], resultado["salteados"])

    return ("{}: {} mails enviados, {} fallidos, {} casillas en el tope del día, {} para la próxima corrida, "
            "{} formularios salteados").format(
        prefijo, resultado["enviados"], resultado["fallidos"], resultado["topados"], resultado["para_despues"],
        resultado["salteados"])


def _foto(animal):

    for foto in sorted(animal.animalimage_set.all(), key=lambda foto: (foto.posicion is None, foto.posicion or 0, foto.id)):
        if foto.image:
            return "{}{}".format(settings.SSL_HOST, foto.image.url)

    return None


def _nombre(animal):
    #va en el asunto: un salto de línea ahí hace que Django rechace el mail entero
    return " ".join((animal.nombre or "").split()) or "El animal"


def _enumerar(nombres):

    if len(nombres) <= 1:
        return "".join(nombres)

    return "{} y {}".format(", ".join(nombres[:-1]), nombres[-1])


def contenido(formularios):
    """(asunto, html) del aviso para una casilla, con sus formularios."""

    adoptados = []
    for formulario in sorted(formularios, key=lambda f: (f.gato.fecha_adopcion, f.gato_id)):
        if formulario.gato not in adoptados:
            adoptados.append(formulario.gato)

    #las sugerencias y el link salen del formulario más nuevo: sus respuestas son las más
    #frescas, y su especie es la que está buscando ahora
    ultimo = max(formularios, key=lambda f: (f.fecha_ingreso or f.created_at, f.id))
    link_postularme = postulacion.link(ultimo)

    if link_postularme:
        sugeridos = postulacion.animales_disponibles(postulacion.original_de(ultimo))
    else:
        sugeridos = Animal.get_all_for_adoption(sort="-fecha_ingreso", tipo=postulacion.tipo_de_animal(ultimo))
    sugeridos = list(sugeridos[:MAX_SUGERIDOS])

    for animal in sugeridos:
        animal.foto_url = _foto(animal)
        sexo = animal.get_sexo_display() if animal.sexo != "D" else ""
        animal.datos_cortos = " · ".join(dato for dato in (sexo, animal.edad, animal.zona) if dato)
        if link_postularme:
            animal.link = "{}{}?id={}".format(settings.SSL_HOST, link_postularme, animal.id)
        else:
            url = animal.get_adoption_url()
            animal.link = url if url.startswith(("http://", "https://")) else settings.SSL_HOST + url

    nombres = [_nombre(animal) for animal in adoptados]
    asunto = "{} ya {} familia".format(_enumerar(nombres), "tienen" if len(nombres) > 1 else "tiene")

    html = render_to_string("email/ya_tiene_familia.html", {
        "adoptados": adoptados,
        "nombres": _enumerar([animal.nombre for animal in adoptados]),
        "varios": len(adoptados) > 1,
        "sugeridos": sugeridos,
        "especie": "perros" if postulacion.tipo_de_animal(ultimo) == "P" else "gatos",
        "url_postularme": "{}{}".format(settings.SSL_HOST, link_postularme) if link_postularme else None,
        "maximo_por_dia": postulacion.MAX_POR_DIA,
        "settings": settings,
    })

    return asunto, html


def mandar(mail, formularios):
    """El aviso a una casilla. True si salió."""

    try:
        asunto, html = contenido(formularios)
        send_html_email(asunto, html, settings.SEND_MAIL, mail)
    except Exception as e:
        #sin el mail en el log: es un dato de quien completó el formulario
        logger.warning("No se pudo mandar el aviso de cierre de los formularios %s: %s",
                       [f.id for f in formularios], type(e).__name__)
        return False

    return True
