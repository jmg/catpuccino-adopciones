from catus.models import Animal
from forms_builder.forms.models import Form, Field
import urllib.parse
from django.conf import settings
from django.utils.safestring import mark_safe


class AdoptionService():

    #dónde queda guardado, en cada FormEntry, lo que trajo respuestas()
    CACHE = "_respuestas_con_pregunta"

    def respuestas(self, form_entry):
        """Las respuestas de un formulario enviado, en el orden del formulario, como
        [(FieldEntry, Field o None)]. None es una respuesta cuya pregunta se borró en el admin.

        Son dos consultas, una vez por FormEntry: queda guardado en el objeto. La página de
        /formularios/<hash>/ y el envío de /pre-adopcion/ leen las mismas respuestas cuatro
        o cinco veces, cada una con un AdoptionService() nuevo, y cada lectura buscaba la
        pregunta de cada respuesta con su propia consulta (FieldEntry.field_id no es una FK):
        con cuarenta preguntas, unas doscientas consultas a forms_field por página.

        Quien cambie un valor tiene que hacerlo sobre estos mismos FieldEntry (como
        set_animal_name_otro), o lo que se lea después en el mismo pedido queda viejo.
        """

        if not form_entry:
            return []

        guardadas = getattr(form_entry, self.CACHE, None)
        if guardadas is not None:
            return guardadas

        #por id es el orden en que se crearon, el del formulario: la primera es el animal
        entradas = list(form_entry.fields.order_by("id"))
        preguntas = Field.objects.in_bulk({entrada.field_id for entrada in entradas})
        guardadas = [(entrada, preguntas.get(entrada.field_id)) for entrada in entradas]

        setattr(form_entry, self.CACHE, guardadas)
        return guardadas

    def get_form_attr(self, form_entry, attr):

        for form_field, field in self.respuestas(form_entry):

            if field is None:
                continue

            if attr.lower() in field.label.lower():
                return form_field.value

        return ""

    def get_form_attrs(self, form_entry, attrs, exact=False, convert_to_str=False):

        values = []
        for form_field, field in self.respuestas(form_entry):

            if field is None:
                continue

            #sin pisar form_field.value: es el de respuestas(), que leen todos
            value = form_field.value
            if convert_to_str and field.field_type == 13:
                try:
                    value = int(float(value))
                except (TypeError, ValueError):
                    pass

            for attr in attrs:

                if not exact:
                    if attr.lower() in field.label.lower():
                        values.append((field.label, value))
                else:
                    if attr.lower() == field.label.lower():
                        values.append((field.label, value))

        return values

    def get_formatted_fields(self, form_fields, photos_html=False, photos_raw=False):

        form_fields = list(form_fields)
        #las preguntas de todas las respuestas en una sola consulta
        preguntas = Field.objects.in_bulk({form_field.field_id for form_field in form_fields})

        fields = []
        for form_field in form_fields:

            field = preguntas.get(form_field.field_id)
            if field is None:
                continue

            if field.field_type == 9:
                url = form_field.value
                value = ""
                if url:
                    try:
                        protocol = "https" if settings.ENV != "LOCAL" else "http"
                        val = "{}://{}/{}".format(protocol, settings.HOST, urllib.parse.quote(url))

                        #solo el HTML que armamos acá se marca como seguro. El resto de
                        #las respuestas las escribe cualquiera que complete el formulario
                        #público, así que tienen que salir escapadas.
                        if not photos_raw:
                            if not photos_html:
                                value = mark_safe("<a target='_blank' href='{}'>{}</a>".format(val, val))
                            else:
                                value = mark_safe("<img src='{}' style='max-width: 100%'>".format(val))
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

        #el animal elegido es siempre la primera respuesta del formulario, pero un
        #formulario sin respuestas no puede tumbar la vista
        respuestas = self.respuestas(form_entry)
        if not respuestas:
            return None

        primera_respuesta, _pregunta = respuestas[0]
        animal_id = primera_respuesta.value

        if str(animal_id) != "0":
            try:
                animal_id = int(animal_id)
                animal = Animal.objects.get(id=animal_id)
            except:
                pass

        return animal

    def get_adoptante(self, estado_form):

        data_attrs = self.get_form_attrs(estado_form.form_entry, ["Nombre y Apellido"], exact=True, convert_to_str=True)

        #se usa al armar el contrato: si el formulario no trae el campo (lo renombraron,
        #es un formulario viejo) devolvemos vacio en vez de cortar el flujo del admin
        if not data_attrs:
            return ""

        return data_attrs[0][1]