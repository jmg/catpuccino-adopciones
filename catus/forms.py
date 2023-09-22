from catus.models import Animal, AnimalImage, CatusUser, Contrato, ContratoPersona, EstadoFormulario
from django.forms import ModelForm, Form, ChoiceField, ImageField, PasswordInput, CharField, DateField, EmailField
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Fieldset, ButtonHolder, Submit, Field
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.forms import AuthenticationForm
from django.utils.safestring import mark_safe
from django.forms import ImageField
from django.forms.widgets import FileInput
from django import forms
from django.conf import settings
from django.utils.translation import ugettext, ugettext_lazy as _


class RequiredFieldsMixin():

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)
        fields_required = getattr(self.Meta, 'fields_required', None)

        for key in self.fields:
            if key in fields_required:
                self.fields[key].required = True


class DatePickerClassFieldsMixin():

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)
        fields_date_picker = getattr(self.Meta, 'date_picker', [])

        for key in self.fields:
            if key in fields_date_picker:
                self.fields[key].widget.attrs['class'] = 'date-picker'
                self.fields[key].widget.attrs['autocomplete'] = 'off'


class EstadoFormularioForm(ModelForm):

    class Meta:
        model = EstadoFormulario
        fields = ['estado', 'gato']

        labels = {
            'gato': 'Gato o Perro',
        }


ANIMAL_BASIC_FIELDS = ['tipo', 'estado', 'nombre', 'edad', 'sexo', 'zona']
ANIMAL_LAST_FIELDS = ['datos']

class AnimalForm(DatePickerClassFieldsMixin, ModelForm):

    estado = ChoiceField(choices=settings.ANIMAL_ESTADO_CHOICES)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.helper = FormHelper()
        self.helper.form_tag = False

        basic_fields = [Field(name) for name in ANIMAL_BASIC_FIELDS]
        last_fields = [Field(name) for name in ANIMAL_LAST_FIELDS]

        layout = Layout(
            Fieldset("Datos del Animal", *basic_fields),
            Fieldset("Descripción del Animal", *last_fields),
        )

        self.helper.layout = layout

    #def clean_estado(self):
    #    self.instance.set_estado(self.cleaned_data.get("estado"))

    class Meta:
        model = Animal
        fields = ANIMAL_BASIC_FIELDS + ANIMAL_LAST_FIELDS

        labels = {
            'Estado': "Publicado en adopción",
        }

        help_texts = {
            'datos': 'Descripción del animal que aparecerá en la web',
            'zona': 'La zona en la que se encuentra.'
        }


class ImagePreviewWidget(FileInput):

    def render(self, name, value, attrs=None, **kwargs):
        input_html = super().render(name, value, attrs=None, **kwargs)
        if value:
            try:
                img_html = mark_safe("<img style='max-width: 100%; width: 100%; margin-top: 10px;' src='/{}'/>".format(value))
            except:
                img_html = ""
        else:
            img_html = ""
        return '{}{}'.format(input_html, img_html)


class AnimalImageForm(ModelForm):

    image = ImageField(label='Fotos', widget=ImagePreviewWidget)

    class Meta:
        model = AnimalImage
        fields = ('image', )


class RequiredImageInlineFormset(forms.models.BaseInlineFormSet):
    """ Makes inline fields required """

    def clean(self):
        # get forms that actually have valid data
        count = 0
        delete_checked = 0
        for form in self.forms:
            try:
                if form.cleaned_data:
                    count += 1
                    if form.cleaned_data['DELETE']:
                        delete_checked += 1
                    if not form.cleaned_data['DELETE']:
                        delete_checked -= 1
            except AttributeError:
                # annoyingly, if a subform is invalid Django explicity raises
                # an AttributeError for cleaned_data
                pass

        # Case no images uploaded
        if count < 1:
            self.raise_error()

        # Case one image added and another deleted
        if delete_checked > 0 and AnimalImage.objects.filter(animal=self.instance).count() == 1:
            self.raise_error()

    def raise_error(self):
        msg = "Al menos una foto del animal es requerida"
        self.errors.append((msg))
        raise forms.ValidationError(msg)


class SignupForm(UserCreationForm):

    email = EmailField(required=True)
    instagram = CharField(label='Instagram', required=True)

    class Meta:
        model = CatusUser
        fields = ("email", "instagram", "password1", "password2")

        labels = {
            "password": _("Contraseña"),
        }

    def __init__(self, *args, **kwargs):
        super(UserCreationForm, self).__init__(*args, **kwargs)

        self.fields["password1"].label = _("Contraseña")
        self.fields["password2"].label = _("Confimar contraseña")

        self.fields["password1"].help_text = ""
        self.fields["password2"].help_text = _("Por favor ingresá la misma contraseña nuevamente.")

        self.fields["instagram"].help_text = _("Para etiquetarte cuando subamos posts a nuestro Instagram.")
        self.fields["email"].help_text = _("A este mail te llegarán los formularios de pre-adopción.")


class UserLoginForm(AuthenticationForm):

    def __init__(self, *args, **kwargs):
        self.error_messages['invalid_login'] = _('El correo o la contraseña ingresados son incorrectos.')
        super(UserLoginForm, self).__init__(*args, **kwargs)

        for fieldname in ['username']:
            self.fields[fieldname].label = 'Email'


class CatusUserForm(ModelForm):

    class Meta:
        model = CatusUser
        fields = ["logo_img", "banner_img", "title", "handle", "description", "email", "facebook", "twitter", "instagram"]

        help_texts = {
            "email": "A este mail te llegarán los formularios de pre-adopción.",
            "instagram": "Te etiquetaremos cuando subamos tus animales a nuestro Instagram."
        }

    def __init__(self, *args, **kwargs):
        super(CatusUserForm, self).__init__(*args, **kwargs)

        self.fields["handle"].label = _("Link a tu perfil")
        self.fields["title"].label = _("Título de tu perfil")
        self.fields["description"].label = _("Descripción de tu perfil")


class ContratoForm(RequiredFieldsMixin, DatePickerClassFieldsMixin, ModelForm):

    class Meta:

        model = Contrato
        exclude = ["contrato_aceptado", "contrato_fecha", "adoptante", "hash", "gato", "estado_formulario", "email_enviado", "created_at", "updated_at"]
        fields_required = ["gato_nombre", "gato_color", "gato_fecha_nacimiento", "gato_edad", "miembro_felis_catus_nombre"]
        date_picker = ["gato_fecha_nacimiento", "gato_vacunacion_antirabica_fecha", "gato_vacunacion_triple_1_dosis_fecha", "gato_vacunacion_triple_2_dosis_fecha", "gato_castrado_fecha", "gato_desparasitado_fecha", "gato_pipeta_antipulgas_fecha", "gato_castracion_fecha_futura", "gato_desparasitado_fecha_2", "perro_vacunacion_quintuple_1_dosis_fecha", "perro_vacunacion_quintuple_2_dosis_fecha", "perro_vacunacion_sextuple_1_dosis_fecha"]

        labels = {
            'gato_nombre': 'Nombre del animal',
            'gato_color': 'Color',
            'gato_sexo': 'Sexo',
            'gato_fecha_nacimiento': 'Fecha de nacimiento (dd/mm/yyyy)',
            'gato_edad': 'Edad aproximada',
            'gato_vacunacion_antirabica': 'Vacunación antirrábica',
            'gato_vacunacion_antirabica_fecha': 'Fecha vacunación antirrábica (dd/mm/yyyy)',
            'gato_vacunacion_antirabica_notas': '(Opcional) Notas sobre vacunación antirrábica.',

            #SOLO GATOS
            'gato_vacunacion_triple_1_dosis': 'Vacunación triple felina 1era dosis',
            'gato_vacunacion_triple_1_dosis_fecha': 'Fecha vacunación triple felina 1era dosis (dd/mm/yyyy)',
            'gato_vacunacion_triple_1_dosis_notas': '(Opcional) Notas sobre vacunación triple felina 1era dosis.',
            'gato_vacunacion_triple_2_dosis': 'Vacunación triple felina 2da dosis',
            'gato_vacunacion_triple_2_dosis_fecha': 'Fecha vacunación triple felina 2da dosis (dd/mm/yyyy)',
            'gato_vacunacion_triple_2_dosis_notas': '(Opcional) Notas sobre vacunación triple felina 2da dosis.',
            #ENDGATOS

            #SOLO PERROS
            'perro_vacunacion_quintuple_1_dosis': 'Vacunación Quintuple 1ra dosis',
            'perro_vacunacion_quintuple_1_dosis_fecha': 'Fecha Vacunación Quintuple 1ra dosis',
            'perro_vacunacion_quintuple_1_dosis_notas': '(Opcional) Notas sobre Vacunación Quintuple 1ra dosis',

            'perro_vacunacion_quintuple_2_dosis': 'Vacunación Quintuple 2da dosis',
            'perro_vacunacion_quintuple_2_dosis_fecha': 'Fecha Vacunación Quintuple 2da dosis',
            'perro_vacunacion_quintuple_2_dosis_notas': '(Opcional) Notas sobre Vacunación Quintuple 2da dosis',

            'perro_vacunacion_sextuple_1_dosis': 'Vacunación Sextuple',
            'perro_vacunacion_sextuple_1_dosis_fecha': 'Fecha Vacunación Sextuple',
            'perro_vacunacion_sextuple_1_dosis_notas': '(Opcional) Notas sobre Vacunación Sextuple',
            #END PERROS

            'gato_castrado': 'Castrado',
            'gato_castrado_fecha': 'Fecha castración (dd/mm/yyyy)',
            'gato_castracion_fecha_futura': 'Fecha estimativa de castración en caso de no estar castrado (dd/mm/yyyy)',
            'gato_castrado_notas': '(Opcional) Notas sobre castración.',
            'gato_desparasitado': 'Desparasitado 1era dosis',
            'gato_desparasitado_fecha': 'Fecha desparasitación 1era (dd/mm/yyyy)',
            'gato_desparasitado_2': 'Desparasitado 2da dosis',
            'gato_desparasitado_fecha_2': 'Fecha desparasitación 2da dosis (dd/mm/yyyy)',
            'gato_desparasitado_notas': '(Opcional) Notas sobre desparasitación.',
            'gato_pipeta_antipulgas': 'Pipeta antipulgas',
            'gato_pipeta_antipulgas_fecha': 'Fecha pipeta antipulgas (dd/mm/yyyy)',
            'gato_pipeta_antipulgas_notas': '(Opcional) Notas sobre pipeta antipulgas.',
            'gato_cuidados_especiales': 'Cuidados especiales',

            'gato_alimento': 'Alimento',
            'gato_pipeta_antipulgas_producto': 'Producto Pipeta Antipulgas',
            'gato_desparasitado_producto': 'Producto Desparasitador',

            'gato_cuidados_especiales': 'Cuidados especiales',

            'miembro_adopcion_nombre': 'Persona a cargo de la adopción y seguimiento',
        }

        help_texts = {
            'gato_vacunacion_antirabica_notas': 'Nota: texto de más de 70 caracteres en este campo podría verse mal si el campo inferior tambien contiene texto.',
            'gato_vacunacion_triple_1_dosis_notas': 'Nota: texto de más de 70 caracteres en este campo podría verse mal si el campo inferior tambien contiene texto.',
            'gato_vacunacion_triple_2_dosis_notas': 'Nota: texto de más de 70 caracteres en este campo podría verse mal si el campo inferior tambien contiene texto.',
            'gato_castrado_notas': 'Nota: texto de más de 100 caracteres en este campo podría verse mal si el campo inferior tambien contiene texto.',
            'gato_desparasitado_notas': 'Nota: texto de más de 100 caracteres en este campo podría verse mal si el campo inferior tambien contiene texto.',
            'gato_pipeta_antipulgas_notas': 'Nota: texto de más de 100 caracteres en este campo podría verse mal si el campo inferior tambien contiene texto.',
            'gato_cuidados_especiales': 'Nota: texto de más de 400 caracteres en este campo podría verse mal.',
        }

        widgets = {
            'gato_vacunacion_antirabica_notas': forms.Textarea(attrs={'style': "height: 60px !important"}),
            'gato_vacunacion_triple_1_dosis_notas': forms.Textarea(attrs={'style': "height: 60px !important"}),
            'gato_vacunacion_triple_2_dosis_notas': forms.Textarea(attrs={'style': "height: 60px !important"}),
            'perro_vacunacion_quintuple_1_dosis_notas': forms.Textarea(attrs={'style': "height: 60px !important"}),
            'perro_vacunacion_quintuple_2_dosis_notas': forms.Textarea(attrs={'style': "height: 60px !important"}),
            'perro_vacunacion_sextuple_1_dosis_notas': forms.Textarea(attrs={'style': "height: 60px !important"}),
            'gato_castrado_notas': forms.Textarea(attrs={'style': "height: 60px !important"}),
            'gato_desparasitado_notas': forms.Textarea(attrs={'style': "height: 60px !important"}),
            'gato_pipeta_antipulgas_notas': forms.Textarea(attrs={'style': "height: 60px !important"}),
        }


class ContratoPersonaForm(RequiredFieldsMixin, DatePickerClassFieldsMixin, ModelForm):

    class Meta:
        model = ContratoPersona
        exclude = ["created_at", "updated_at"]
        fields_required = ["persona_nombre", "persona_dni", "persona_fecha_nacimiento", "persona_ocupacion", "persona_celular", "persona_direccion",
        "persona_localidad"]
        date_picker = ["persona_fecha_nacimiento"]

        labels = {
            'persona_nombre': 'Nombre y Apellido',
            'persona_dni': 'DNI',
            'persona_fecha_nacimiento': 'Fecha de nacimiento (dd/mm/yyyy)',
            'persona_ocupacion': 'Ocupación',
            'persona_celular': 'Celular',
            'persona_direccion': 'Dirección',
            'persona_localidad': 'Localidad',
            'persona_instagram': 'Instagram',
            'persona_facebook': 'Facebook',
            'persona_email': 'Email',
        }