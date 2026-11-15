"""Postularse a otro animal con las respuestas de un formulario ya enviado.

Pedido del equipo (2026-11-15): quien completó el formulario de pre-adopción no tiene que
escribir cuarenta respuestas de nuevo para postularse a otro animal. En el sitio no hay
cuentas de adoptante, y no hacen falta: el "perfil" de la persona es el formulario que ya
mandó, y lo abre con un link privado que recibe al enviarlo (en la página de "formulario
enviado" y en el mail de confirmación).

El link lleva un token firmado (django.core.signing) con el id del formulario original: no se
puede adivinar ni alterar, vence solo y no necesita guardarse en la base. No es el hash del
formulario: ese lo conocen el rescatista y el equipo, y con él cualquiera de ellos podría
postular a la persona a otros animales.

Postularse crea un formulario nuevo para el otro animal, con las mismas respuestas y las
mismas fotos, que le llega a quien lo publicó como cualquier otro. Queda anotado de qué
formulario salió (EstadoFormulario.copiado_de): el rescatista tiene que saber que las
respuestas se escribieron para otro animal y pueden nombrarlo. Las copias apuntan siempre al
original, también cuando el link se abrió desde el mail de una copia.

Límites: solo entre animales de la misma especie (el formulario de perros tiene otras
preguntas), nunca dos veces al mismo animal, y MAX_POR_DIA por persona, porque cada
postulación le manda un mail a un rescatista.
"""
import uuid
from datetime import timedelta

from django.core import signing
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from forms_builder.forms.models import FieldEntry, FormEntry

from catus.models import Animal, EstadoFormulario
from catus.services.buenadoptante import TIPOS_PREADOPCION

SAL = "postularse-a-otro-animal"
VIGENCIA_DIAS = 60
MAX_POR_DIA = 3


class NoSePuede(Exception):
    """Por qué no se pudo postular. El mensaje se le muestra a la persona."""


def original_de(estado):
    """El formulario que la persona completó a mano: el mismo, o aquel del que es copia."""

    return estado.copiado_de or estado


def token(estado):

    return signing.dumps(original_de(estado).id, salt=SAL)


def link(estado):
    """La ruta del link privado, o None si con este formulario no se puede postular a otro
    (tránsito, o frenado por BuenAdoptante)."""

    if estado is None or estado.tipo not in TIPOS_PREADOPCION or estado.estado == "B" or estado.form_entry_id is None:
        return None

    return "/postularme/{}/".format(token(estado))


def formulario_del_token(texto):
    """El formulario original al que apunta el link, o None si el link no sirve: está mal
    escrito, venció, el formulario ya no existe o no es de pre-adopción.

    Tampoco sirve si BuenAdoptante frenó ese formulario o alguna de sus copias: la persona no
    se entera del motivo (ver PreAdoptionView.avisar_bloqueo), y cada intento nuevo le
    mandaría otro aviso al equipo.
    """

    try:
        estado_id = signing.loads(texto or "", salt=SAL, max_age=VIGENCIA_DIAS * 24 * 60 * 60)
    except signing.BadSignature:
        #SignatureExpired también es BadSignature
        return None

    estado = (EstadoFormulario.objects.filter(id=estado_id, tipo__in=TIPOS_PREADOPCION, form_entry__isnull=False)
              .select_related("gato", "copiado_de").first())
    if estado is None:
        return None

    original = original_de(estado)
    if original.form_entry_id is None or original.tipo not in TIPOS_PREADOPCION:
        return None
    if original.estado == "B" or EstadoFormulario.objects.filter(copiado_de=original, estado="B").exists():
        return None

    return original


def postulaciones(original):
    """El formulario original y sus copias, del más viejo al más nuevo."""

    return list(EstadoFormulario.objects.filter(Q(id=original.id) | Q(copiado_de=original))
                .select_related("gato").order_by("fecha_ingreso", "id"))


def tipo_de_animal(original):

    return "P" if original.tipo == "AP" else "G"


def animales_disponibles(original):
    """Los animales en adopción de la misma especie a los que la persona todavía no se
    postuló, los publicados más recientes primero."""

    ya_postulados = [p.gato_id for p in postulaciones(original) if p.gato_id]
    return (Animal.get_all_for_adoption(sort="-fecha_ingreso", tipo=tipo_de_animal(original))
            .exclude(id__in=ya_postulados))


def cupo(original):
    """A cuántos animales más se puede postular hoy (en las últimas 24 horas)."""

    desde = timezone.now() - timedelta(hours=24)
    usadas = EstadoFormulario.objects.filter(copiado_de=original, fecha_ingreso__gte=desde).count()
    return max(0, MAX_POR_DIA - usadas)


def postular(original, animal_id):
    """Crea el formulario para otro animal con las respuestas del original y lo devuelve.

    Levanta NoSePuede si el animal no está disponible para esta persona o si ya usó el cupo
    del día. No manda mails ni consulta a BuenAdoptante: eso lo hace la vista, igual que con
    un formulario recién completado.
    """

    try:
        animal_id = int(animal_id)
    except (TypeError, ValueError):
        raise NoSePuede("Elegí a qué animal querés postularte.")

    with transaction.atomic():
        #la fila del original queda tomada hasta el final: dos envíos pegados no se
        #saltean el cupo ni se postulan dos veces al mismo animal
        original = EstadoFormulario.objects.select_for_update().get(id=original.id)

        if cupo(original) <= 0:
            raise NoSePuede("Por hoy ya te postulaste a {} animales con estas respuestas. "
                            "Mañana podés postularte a otros.".format(MAX_POR_DIA))

        animal = animales_disponibles(original).filter(id=animal_id).first()
        if animal is None:
            raise NoSePuede("Ese animal ya no está en adopción, o ya te habías postulado.")

        respuestas = list(original.form_entry.fields.all().order_by("id"))
        if not respuestas:
            raise NoSePuede("No encontramos las respuestas de tu formulario. Completalo de nuevo desde la ficha del animal.")

        entry = FormEntry.objects.create(form=original.form_entry.form, entry_time=timezone.now())
        copias = [FieldEntry(entry=entry, field_id=respuesta.field_id, value=respuesta.value) for respuesta in respuestas]
        #el animal elegido es siempre la primera respuesta (AdoptionService.get_animal_obj)
        copias[0].value = str(animal.id)
        FieldEntry.objects.bulk_create(copias)

        return EstadoFormulario.objects.create(
            form_entry=entry,
            persona_nombre=original.persona_nombre,
            hash=str(uuid.uuid4()),
            gato=animal,
            tipo=original.tipo,
            fecha_ingreso=timezone.now(),
            copiado_de=original,
        )
