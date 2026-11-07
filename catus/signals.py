import logging

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from forms_builder.forms.models import Form, Field
from catus.models import Animal

logger = logging.getLogger(__name__)


#El desplegable "a quién te gustaría adoptar" del formulario público se mantiene
#sincronizado con los animales en adopción. Los campos se ubican por su etiqueta:
#buscar el de gatos por posición (Field.objects.all()[0]) era una lotería, porque
#hay cuatro campos con el mismo orden en formularios distintos y el desempate lo
#hacía la base. Si le tocaba otro, le pisaba las opciones a un campo de texto.
ANIMAL_FIELD_LABELS = {
    "G": "Gato a adoptar",
    "P": "Perro a adoptar",
}


def _update_animal_field(tipo):

    #esto corre en cada save de un animal, así que se traen los dos primeros de una sola
    #consulta: alcanza para saber si hay más de uno con la misma etiqueta.
    campos = list(Field.objects.filter(label=ANIMAL_FIELD_LABELS[tipo])[:2])

    #si alguien le cambia la etiqueta al campo en /forms/, acá no se encuentra nada y el
    #desplegable se queda congelado para siempre: los animales nuevos no aparecen y el
    #formulario público los rechaza. Salir mudo dejaba eso sin una sola línea de log.
    if not campos:
        logger.warning(
            "No se encontró el campo '%s' (%s) del formulario: el desplegable de animales queda desactualizado",
            ANIMAL_FIELD_LABELS[tipo], tipo,
        )
        return

    if len(campos) > 1:
        logger.warning(
            "Hay más de un campo con la etiqueta '%s' (%s): se actualiza solo el primero",
            ANIMAL_FIELD_LABELS[tipo], tipo,
        )

    animal_field = campos[0]

    #el "0" es la opción "otro animal". Concatenar con format dejaba un "0," suelto
    #cuando no hay animales, y eso agrega una opción vacía al desplegable público.
    ids = [str(animal.id) for animal in Animal.get_all_for_adoption(tipo=tipo)]
    new_choices = ",".join(["0"] + ids)

    if new_choices != animal_field.choices:
        animal_field.choices = new_choices
        animal_field.save()


def _update_form_field():

    #esto corre dentro del save de un animal: nunca puede hacerlo fallar. Pero
    #tampoco puede fallar en silencio, porque si se desincroniza la gente no puede
    #elegir al animal que quiere adoptar. Y un problema con los gatos no tiene por
    #qué dejar desactualizados a los perros.
    for tipo in ANIMAL_FIELD_LABELS:
        try:
            _update_animal_field(tipo)
        except Exception:
            logger.exception("No se pudo actualizar el campo de animales (%s) del formulario", tipo)


@receiver(post_save, sender=Animal)
def animal_post_save(sender, instance, created, **kwargs):
    _update_form_field()


@receiver(post_delete, sender=Animal)
def animal_post_delete(sender, instance, **kwargs):
    _update_form_field()


@receiver(post_save, sender=Form)
def form_post_save(sender, instance, **kwargs):
    _update_form_field()


@receiver(post_delete, sender=Form)
def form_post_delete(sender, instance, **kwargs):
    _update_form_field()