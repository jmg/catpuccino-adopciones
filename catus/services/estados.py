"""Los cambios de estado de un animal: un solo camino para todas las pantallas.

Un animal está en adopción (D), reservado (R), adoptado (A) o expirado (E). Cada pantalla
cambiaba el estado a su manera, y la edición lo hacía mal: elegir "Adoptado" en el selector
lo dejaba sin fecha de adopción, y el panel solo pregunta "¿Quién lo adoptó?" si la hay (de
35 adopciones en 90 días, 15 se marcaron así y quedaron sin fecha, sin adoptante y sin
registro en BuenAdoptante); pasar de "Expirado" a "En adopción" no renovaba fecha_ingreso, y
expirar_animales lo volvía a sacar a la mañana siguiente. Ahora la edición del animal, los
botones del panel y el mail de expiración pasan por acá, y lo que se agregue también.

Lo que hace cada uno:

- marcar_adoptado: estado A y la fecha de adopción, que no se pisa si ya estaba adoptado (a
  uno adoptado se le puede decir después quién lo adoptó). Con el formulario de quien
  adoptó, deja el animal vinculado, marca ese formulario como adoptado y anota la adopción
  para BuenAdoptante, que la manda el cron enviar_buenadoptante. Sin formulario, el panel le
  pregunta al rescatista quién fue. El comentario "adoptado" en Instagram no se pide acá: lo
  pone el cron update_status_in_ig a todo animal en A con el posteo publicado.
- republicar: estado D, sin fecha de adopción ni de expiración. Si no estaba en adopción
  (expirado, reservado o adoptado) le arranca de nuevo el mes, porque expirar_animales lo
  cuenta desde fecha_ingreso: un reservado de hace dos meses que vuelve a adopción se
  expiraba a la mañana siguiente. Si venía de expirado o adoptado, el panel vuelve a hacer
  sus preguntas ("No republicar" y "nadie de la lista" las apagaban).
- reservar: estado R, sin fecha de adopción. No se ve en el sitio y el cron no lo expira.
- expirar: a mano, sin expiro_el, que es lo que distingue al que expiró el cron: por ese
  el panel y el mail preguntan si sigue en adopción; por el que sacó una persona, no.

expiro_el solo lo vacían republicar y expirar a mano. A un adoptado o reservado se le deja:
con estado distinto de E no pregunta nada, y queda el dato de que el cron lo había expirado
(cuántos de los expirados terminaron adoptados).

Todas cambian el animal y lo guardan con save(), que también actualiza el desplegable de
animales del formulario público (signals). cambiar_estado(..., guardar=False) es para quien
guarda el animal por su cuenta, como la edición, que lo guarda junto con el resto del form.
"""
from django.utils import timezone

from catus.models import EstadoFormulario
from catus.services.buenadoptante import TIPOS_PREADOPCION, BuenAdoptanteService

EN_ADOPCION = "D"
RESERVADO = "R"
ADOPTADO = "A"
EXPIRADO = "E"

ESTADOS = (EN_ADOPCION, RESERVADO, ADOPTADO, EXPIRADO)

#los formularios que no pueden ser "quien lo adoptó": los frenados por BuenAdoptante (el
#rescatista ni los recibió) y los duplicados
ESTADOS_FORMULARIO_NO_ADOPTANTE = ("B", "U")


def _aplicar(animal, estado):
    """Lo que cambia en el animal al pasar a `estado`. No guarda."""

    if estado not in ESTADOS:
        raise ValueError("Estado de animal desconocido: {!r}".format(estado))

    ahora = timezone.now()
    anterior = animal.estado

    if estado == ADOPTADO:
        if anterior != ADOPTADO or animal.fecha_adopcion is None:
            animal.fecha_adopcion = ahora
    else:
        #fuera de A la fecha de adopción no significa nada, y dejarla confunde al panel
        animal.fecha_adopcion = None

    if estado == EN_ADOPCION:
        if anterior != EN_ADOPCION:
            animal.fecha_ingreso = ahora
        if anterior in (EXPIRADO, ADOPTADO):
            animal.pregunta_adopcion_hasta = None
        animal.expiro_el = None

    if estado == EXPIRADO:
        animal.expiro_el = None

    animal.estado = estado
    return animal


def cambiar_estado(animal, estado, guardar=True):
    """Pasa el animal a `estado` (D, R, A o E) con todo lo que eso implica. Sin formulario
    de adoptante: para elegirlo, marcar_adoptado."""

    _aplicar(animal, estado)

    if guardar:
        animal.save()

    return animal


def marcar_adoptado(animal, formulario=None):
    """Adoptado, con la fecha. `formulario` es el EstadoFormulario de quien lo adoptó, si
    se sabe: buscalo con formulario_del_adoptante, que controla que sea del rescatista."""

    _aplicar(animal, ADOPTADO)

    if formulario is not None:
        animal.estado_formulario = formulario
        animal.adoptante = (formulario.get_persona() or "")[:255] or None

    animal.save()

    if formulario is not None:
        if formulario.estado != "A":
            formulario.estado = "A"
            formulario.save(update_fields=["estado"])

        BuenAdoptanteService().registrar_adopcion(formulario, animal)

    return animal


def republicar(animal):

    return cambiar_estado(animal, EN_ADOPCION)


def reservar(animal):

    return cambiar_estado(animal, RESERVADO)


def expirar(animal):
    """A mano. El cron expirar_animales no pasa por acá: hace un UPDATE de todos juntos."""

    return cambiar_estado(animal, EXPIRADO)


def formulario_del_adoptante(animal, formulario_id):
    """El formulario de pre-adopción que el rescatista eligió como "quien lo adoptó", o None.

    Tiene que ser de un animal del mismo rescatista: quien pidió un gato a veces termina
    adoptando otro. Así no se puede vincular el formulario de un rescatista ajeno. El id
    llega del navegador: cualquier cosa que no sea un número es None.
    """

    if not formulario_id or not str(formulario_id).isdigit():
        return None

    return (EstadoFormulario.objects
            .filter(id=formulario_id, gato__cargado_por_id=animal.cargado_por_id, tipo__in=TIPOS_PREADOPCION)
            .exclude(estado__in=ESTADOS_FORMULARIO_NO_ADOPTANTE).first())
