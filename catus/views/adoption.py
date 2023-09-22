import json
import random
import uuid
from forms_builder.forms.forms import FormForForm
from forms_builder.forms.models import Form, Field, FieldEntry

from catus.models import Animal, CatusUser, EstadoFormulario
from catus.utils import send_html_email
from catus.services.adoption import AdoptionService

from django.template import Context
from django.conf import settings
from django.utils import timezone
from catus.views.home import BaseView


class ListView(BaseView):

    url = r"^adopciones/$"

    def render_to_response(self, context):

        context["animals"] = Animal.get_all_for_adoption(sort="{}nombre".format(random.choice(["", "-"])))
        context["perros_en_adopcion"] = bool([animal for animal in context["animals"] if animal.tipo == "P"])

        return BaseView.render_to_response(self, context)


class PreAdoptionView(BaseView):

    url = r"^pre-adopcion/$"
    form_type = "preadoption"
    animal_type = "gato"

    def render_to_response(self, context):

        animals = []
        tipo = "P" if self.animal_type == "perro" else "G"

        user_id = self.request.GET.get("user_id")
        extra_filters = {}
        if user_id:
            try:
                extra_filters["cargado_por"] = CatusUser.objects.get(id=user_id)
            except:
                pass

        animals_objs = Animal.get_all_for_adoption(sort="nombre", tipo=tipo, extra_filters=extra_filters)
        for animal in animals_objs:
            animals.append({"name": str(animal), "id": animal.id})

        animals = json.dumps(animals)
        context["animals"] = animals

        form = self._get_form()
        animal_id = self.request.GET.get("id")

        context["form_for_form"] = FormForForm(form, Context(context), None, None)
        context["form"] = form
        context["is_post"] = False

        context["hidden_terms_cookie"] = "hidden-terms-{}".format(self.form_type)
        context["accepted_terms_cookie"] = "accepted-terms-{}-{}".format(self.form_type, self.animal_type)
        context["form_type"] = self.form_type
        context["animal_type"] = self.animal_type
        context["is_user"] = True if user_id else False

        if self.form_type == "preadoption":

            if self.animal_type == "gato":
                context["post_url"] = "/pre-adopcion/"
            elif self.animal_type == "perro":
                context["post_url"] = "/pre-adopcion/perros/"

        elif self.form_type == "transit":

            if self.animal_type == "gato":
                context["post_url"] = "/transito/"
            elif self.animal_type == "perro":
                context["post_url"] = "/transito/perros/"

        if animal_id:
            try:
                animal = Animal.objects.filter(id=animal_id)
                context["animal"] = animal[0]
            except:
                pass

        return BaseView.render_to_response(self, context)

    def _get_form(self):

        return Form.objects.all()[0]

    def post(self, *a, **k):

        post = getattr(self.request, "POST", None)
        files = getattr(self.request, "FILES", None)

        animal_id = self.request.GET.get("id")

        context = {"request": self.request }

        form = self._get_form()
        form_for_form = FormForForm(form, Context(context), post, files)

        response_context = {}
        response_context["form_for_form"] = form_for_form
        response_context["form"] = form
        response_context["is_post"] = True

        if form_for_form.errors:
            response_context["errors"] = form_for_form.errors
            response_context["success"] = False
            return BaseView.render_to_response(self, response_context)

        form_entry = form_for_form.save()

        if self.form_type == "preadoption":
            animal = AdoptionService().get_animal_obj(form_entry)
            animal_name = AdoptionService().get_animal(form_entry)
        else:
            animal = None
            animal_name = None

        try:
            persona_nombre = AdoptionService().get_form_attr(form_entry, "Nombre y Apellido")
        except:
            persona_nombre = None

        if self.form_type == "preadoption":
            if self.animal_type == "perro":
                tipo = "AP"
            else:
                tipo = "A"
        else:
            if self.animal_type == "perro":
                tipo = "TP"
            else:
                tipo = "T"

        estado = EstadoFormulario(
            form_entry=form_entry,
            persona_nombre=persona_nombre,
            hash=str(uuid.uuid4()),
            gato=animal,
            tipo=tipo,
            fecha_ingreso=timezone.now(),
        )
        estado.save()

        self.send_email(form_entry, form_for_form, animal_name, estado)
        response_context["success"] = True
        return BaseView.render_to_response(self, response_context)

    def find_form_same_person(self, form_entry, persona_nombre, tipo):

        same_person = FieldEntry.objects.filter(value=persona_nombre)
        if same_person:
            same_person = same_person[0]
            estado = EstadoFormulario.objects.filter(form_entry=same_person.entry, tipo=tipo)
            if estado:
                return estado[0]

    def _get_form_fields(self, form_entry):

        return [x for x in form_entry.fields.all()[1:]]

    def _get_email_template(self):

        return "email/form.html"

    def set_animal_name_otro(self, form_entry, value):

        for form_field in form_entry.fields.all():

            try:
                field = Field.objects.get(id=form_field.field_id)
            except:
                continue

            if "Nombre del gato a adoptar" in field.label:
                form_field.value = value
                form_field.save()

    def send_email(self, form_entry, form_for_form, animal, estado):

        if self.form_type == "preadoption":

            subject = "Nuevo formulario de pre-adopción para: {}".format(animal)
            self.set_animal_name_otro(form_entry, str(animal))

        elif self.form_type == "transit":

            if self.animal_type == "perro":
                subject = "Nuevo formulario de tránsito - Perros"
            else:
                subject = "Nuevo formulario de tránsito - Gatos"

        form_fields = self._get_form_fields(form_entry)
        fields = AdoptionService().get_formatted_fields(form_fields)

        email_context = {"animal": animal, "fields": fields, "form_hash": estado.hash, "settings": settings}
        content = self.render(self._get_email_template(), email_context)

        to_emails = list(set(["catpuccino.ok@gmail.com", animal.cargado_por.email]))
        send_html_email(subject, content, settings.SEND_MAIL, to_emails)

        try:
            email = AdoptionService().get_form_attr(form_entry, "Email")
        except:
            email = None

        if not email:
            return

        email_context = {
            "animal": animal,
            "tipo": self.form_type,
        }

        subject = "Catpuccino Adopciones - Formulario Recibido"
        content = self.render("email/received.html", email_context)

        try:
            send_html_email(subject, content, settings.SEND_MAIL, email)
        except:
            pass


class PreAdoptionPerrosView(PreAdoptionView):

    url = r"^pre-adopcion/perros/$"
    form_type = "preadoption"
    animal_type = "perro"
    template_name = "adoption/preadoption.html"

    def _get_form(self):

        return Form.objects.all()[3]

