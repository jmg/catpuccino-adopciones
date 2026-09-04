"""Objetos de prueba, para que cada test diga solo lo que le importa."""
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from forms_builder.forms.models import Field, FormEntry

from catus.models import Animal, AnimalImage, CatusUser, EstadoFormulario


def make_user(email="rescatista@catpuccino.test", **kwargs):

    kwargs.setdefault("username", email)
    return CatusUser.objects.create(email=email, **kwargs)


def make_animal(nombre="Willy", **kwargs):

    kwargs.setdefault("estado", "D")
    kwargs.setdefault("aprobado", True)
    kwargs.setdefault("tipo", "G")
    kwargs.setdefault("fecha_ingreso", timezone.now())
    return Animal.objects.create(nombre=nombre, **kwargs)


def make_estado_formulario(animal=None, **kwargs):

    kwargs.setdefault("hash", "hash-de-prueba")
    kwargs.setdefault("estado", "N")
    kwargs.setdefault("fecha_ingreso", timezone.now())
    return EstadoFormulario.objects.create(gato=animal, **kwargs)


def make_form_entry(form, **kwargs):
    """Una respuesta enviada al formulario público."""

    #entry_time en forms_builder es NOT NULL y no tiene default: crear la entry
    #sin fecha tira IntegrityError y el test ni llega a correr.
    kwargs.setdefault("entry_time", timezone.now())
    return FormEntry.objects.create(form=form, **kwargs)


def make_field(form, label, field_type=1, **kwargs):
    """Un campo del formulario público (field_type 1 = texto de una línea)."""

    #el form no es opcional: Field.save() numera el orden con self.form.fields.count(),
    #así que sin form revienta antes de guardar.
    return Field.objects.create(form=form, label=label, field_type=field_type, **kwargs)


def photo_bytes(size=(800, 600), color=(120, 120, 120), fmt="JPEG"):
    """Una foto real en memoria: los tests de imagenes necesitan pixeles de verdad."""

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format=fmt)
    buffer.seek(0)
    return buffer


def uploaded_photo(name="foto.jpg", size=(800, 600)):

    return SimpleUploadedFile(name, photo_bytes(size).getvalue(), content_type="image/jpeg")


def make_animal_image(animal=None, size=(800, 600), **kwargs):

    if animal is None:
        animal = make_animal()

    image = AnimalImage(animal=animal, **kwargs)
    image.image.save("foto.jpg", uploaded_photo(size=size), save=True)
    return image
