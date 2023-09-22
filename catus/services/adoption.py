from catus.models import Animal
from forms_builder.forms.models import Form, Field
import urllib.parse
from django.conf import settings


class AdoptionService():

    def get_form_attr(self, form_entry, attr):

        if not form_entry:
            return ""

        for form_field in form_entry.fields.all():

            try:
                field = Field.objects.get(id=form_field.field_id)
            except:
                continue

            if attr.lower() in field.label.lower():
                return form_field.value

        return ""

    def get_form_attrs(self, form_entry, attrs, exact=False, convert_to_str=False):

        if not form_entry:
            return ""

        values = []
        for form_field in form_entry.fields.all():

            try:
                field = Field.objects.get(id=form_field.field_id)
            except:
                continue

            for attr in attrs:

                if convert_to_str:
                    if field.field_type == 13:
                        try:
                            form_field.value = int(float(form_field.value))
                        except:
                            pass

                if not exact:
                    if attr.lower() in field.label.lower():
                        values.append((field.label, form_field.value))
                else:
                    if attr.lower() == field.label.lower():
                        values.append((field.label, form_field.value))

        return values

    def get_formatted_fields(self, form_fields, photos_html=False, photos_raw=False):

        fields = []
        for form_field in form_fields:

            try:
                field = Field.objects.get(id=form_field.field_id)
            except:
                continue

            if field.field_type == 9:
                url = form_field.value
                value = ""
                if url:
                    try:
                        protocol = "https" if settings.ENV != "LOCAL" else "http"
                        val = "{}://{}/{}".format(protocol, settings.HOST, urllib.parse.quote(url))

                        if not photos_raw:
                            if not photos_html:
                                value = "<a target='_blank' href='{}'>{}</a>".format(val, val)
                            else:
                                value = "<img src='{}' style='max-width: 100%'>".format(val)
                        else:
                            value = val
                    except:
                        pass

            elif field.field_type == 13:
                try:
                    value = int(float(form_field.value))
                except:
                    value = form_field.value

            else:
                value = form_field.value

            fields.append((field.label, value))

        return fields

    def get_animal(self, form_entry):

        if not form_entry:
            return ""

        animal = self.get_animal_obj(form_entry)
        if not animal:
            animal = self.get_form_attr(form_entry, "Nombre del gato a adoptar")

        return animal

    def get_animal_obj(self, form_entry):

        if not form_entry:
            return None

        animal = None
        animal_id = [x.value for x in form_entry.fields.all()][0]

        if str(animal_id) != "0":
            try:
                animal_id = int(animal_id)
                animal = Animal.objects.get(id=animal_id)
            except:
                pass

        return animal

    def get_adoptante(self, estado_form):

        data_attrs = self.get_form_attrs(estado_form.form_entry, ["Nombre y Apellido"], exact=True, convert_to_str=True)
        return data_attrs[0][1]