"""Las respuestas del formulario público salen escapadas en /formularios/<hash>/.

Las escribe cualquiera, sin cuenta. El template pintaba toda respuesta de texto que
terminara en .mp4 o .webm como <a href="{{value}}" download>Descargar video</a>: un
candidato respondía "javascript:fetch(...)//a.mp4" y el JS corría en la sesión del
rescatista o del equipo que tocaba el botón (revisión de la semana del 2026-11-12). Los
videos de verdad son archivos subidos y no pasaban por ese camino.
"""
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase

from forms_builder.forms.models import FieldEntry, Form

from catus.tests.factories import make_animal, make_estado_formulario, make_field, make_form_entry, make_user
from catus.views.forms import FormView


class RespuestasEscapadasTest(TestCase):

    def setUp(self):

        self.rescatista = make_user(email="respuestas@catpuccino.test")
        animal = make_animal(nombre="Willy", cargado_por=self.rescatista)

        form = Form.objects.create(title="Pre Adopción")
        entry = make_form_entry(form)
        #la vista saltea la primera respuesta de los formularios de pre-adopción
        primero = make_field(form, "Nombre del gato a adoptar")
        texto = make_field(form, "Video del lugar donde va a vivir")
        archivo = make_field(form, "Subí un video", field_type=9)
        FieldEntry.objects.create(entry=entry, field_id=primero.id, value=str(animal.id))
        FieldEntry.objects.create(entry=entry, field_id=texto.id, value="javascript:fetch('/x')//a.mp4")
        FieldEntry.objects.create(entry=entry, field_id=archivo.id, value="forms/patio.mov")

        make_estado_formulario(animal=animal, hash="respuestas123", tipo="A", form_entry=entry)

    def ver(self):

        request = RequestFactory().get("/formularios/respuestas123/")
        request.user = self.rescatista
        SessionMiddleware(lambda request: None).process_request(request)
        response = FormView.as_view(template_name="forms/form.html")(request, form_hash="respuestas123")
        response.render()
        return response.content.decode()

    def test_una_respuesta_que_termina_en_mp4_no_es_un_link(self):

        html = self.ver()

        self.assertNotIn('href="javascript:', html)
        self.assertNotIn("<source src=\"javascript:", html)
        self.assertIn("javascript:fetch(&#x27;/x&#x27;)//a.mp4", html)

    def test_el_video_subido_sigue_llegando_con_la_url_del_sitio(self):

        html = self.ver()

        self.assertIn("/forms/patio.mov", html)
