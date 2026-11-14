"""Las adopciones anteriores de una persona en el sitio, para el recuadro "Ya adoptó por
Catpuccino" de la página de un formulario (FormView). Pedido del equipo: el rescatista ve si
quien le escribe ya adoptó antes por el sitio, con qué animal y cuándo.

La persona se reconoce por su mail o su celular en otros formularios de pre-adopción, con las
mismas reglas que se usan para BuenAdoptante (BuenAdoptanteService.persona): un dato de
relleno ("no tengo", 0000000000, no@no.com) no es de nadie y no se compara. El celular se
compara por sus últimos 8 dígitos, el número local, porque la gente lo escribe con y sin 54, 9,
011 o 15.

Solo se miran los formularios que terminaron en adopción: los marcados "Adoptado" y los que
quedaron vinculados a un animal (Animal.estado_formulario, al elegir quién lo adoptó). Son unos
cientos, así que se leen sus respuestas de una vez, en vez de recorrer todos los formularios.
"""
import re

from django.db.models import Q
from forms_builder.forms.models import Field, FieldEntry

from catus.models import Animal, EstadoFormulario
from catus.services.buenadoptante import TIPOS_PREADOPCION, BuenAdoptanteService


def _identificadores(persona):
    """(mail, últimos 8 dígitos del celular) de lo que arma BuenAdoptanteService.persona."""

    mail = (persona.get("email") or "").strip().lower()
    digitos = re.sub(r"\D", "", persona.get("phone") or "")
    return mail, (digitos[-8:] if len(digitos) >= 8 else "")


def adopciones_anteriores(estado_form):
    """[{animal, tipo, fecha}] de otras adopciones de la misma persona, la más nueva primero.
    No cuenta la del animal de este mismo formulario: si mandó dos formularios por el mismo
    animal, es la misma adopción."""

    if estado_form is None or estado_form.form_entry_id is None:
        return []

    servicio = BuenAdoptanteService()
    mail, celular = _identificadores(servicio.persona(servicio.respuestas(estado_form.form_entry)))
    if not mail and not celular:
        return []

    #formulario -> animal que quedó vinculado a él al elegir quién lo adoptó
    vinculados = dict(Animal.objects.filter(estado_formulario__isnull=False)
                      .values_list("estado_formulario_id", "id"))
    adoptados = list(EstadoFormulario.objects
                     .filter(tipo__in=TIPOS_PREADOPCION, form_entry__isnull=False)
                     .filter(Q(estado="A") | Q(id__in=list(vinculados)))
                     .exclude(id=estado_form.id)
                     .values_list("id", "form_entry_id", "gato_id", "updated_at"))
    if not adoptados:
        return []

    etiquetas = dict(Field.objects.filter(
        Q(label__icontains="email") | Q(label__icontains="celular") | Q(label__icontains="teléfono")
        | Q(label__icontains="telefono")).values_list("id", "label"))
    respuestas = {}
    for entry_id, field_id, valor in FieldEntry.objects.filter(
            entry_id__in=[entry for _, entry, _, _ in adoptados], field_id__in=list(etiquetas)).values_list(
            "entry_id", "field_id", "value"):
        respuestas.setdefault(entry_id, {})[(etiquetas[field_id] or "").strip()] = valor or ""

    coincidencias = {}
    for form_id, entry_id, gato_id, actualizado in adoptados:
        otro_mail, otro_celular = _identificadores(servicio.persona(respuestas.get(entry_id, {})))
        if not ((mail and otro_mail == mail) or (celular and otro_celular == celular)):
            continue
        animal_id = vinculados.get(form_id) or gato_id
        if animal_id is None or animal_id == estado_form.gato_id or animal_id in coincidencias:
            continue
        coincidencias[animal_id] = actualizado

    if not coincidencias:
        return []

    resultado = []
    for animal_id, nombre, tipo, fecha_adopcion in Animal.objects.filter(id__in=list(coincidencias)).values_list(
            "id", "nombre", "tipo", "fecha_adopcion"):
        resultado.append({"animal": nombre or "Sin nombre", "tipo": "perro" if tipo == "P" else "gato",
                          "fecha": fecha_adopcion or coincidencias[animal_id]})
    resultado.sort(key=lambda a: a["fecha"], reverse=True)
    return resultado
