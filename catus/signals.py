from django.contrib.auth.models import User
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from forms_builder.forms.models import Form, Field
from catus.models import Animal


def _update_animal_field(tipo):

    if tipo == "G":
        animal_field = Field.objects.all()[0]
    else:
        animal_field = Field.objects.filter(label="Perro a adoptar")
        if not animal_field:
            return
        else:
            animal_field = animal_field[0]

    new_choices = "0,{}".format(",".join([str(animal.id) for animal in Animal.get_all_for_adoption(tipo=tipo)]))
    if new_choices != animal_field.choices:
        animal_field.choices = new_choices
        animal_field.save()


def _update_form_field():

    try:
        _update_animal_field("G")
        _update_animal_field("P")
    except:
        pass


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