"""El carrusel con las fotos del animal en el formulario público de pre-adopción.

La página arma un carrusel de lightSlider (en loop y con autoplay) cada vez que llegan
las fotos de /animal/photos/: al entrar con ?id, otra vez al tocar "Aceptar y Completar
el Formulario" (showForm() las vuelve a pedir) y al cambiar el animal en el desplegable.
Para rearmarlo se llamaba a slider.destroy(), y el destroy() de lightSlider 1.1.6
(catus/static/slider/js/) deja sus slides en null sin cancelar el reacomodo que el loop
programa al dar la vuelta: un setTimeout de medio segundo en resetSlide(). Si las fotos
llegaban en ese medio segundo, ese timer corría sobre el carrusel destruido y a quien
estaba completando el formulario le saltaba en el navegador "TypeError: Cannot read
properties of null (reading 'removeClass')". El carrusel nuevo ya estaba armado, así que
no se veía nada raro, pero cada vez llegaba a Jentry como un error de la página. El
carrusel da la vuelta cada dos segundos por foto (seis con tres fotos), así que alcanzaba
con aceptar los requisitos en el momento justo.

La suite no tiene un motor de JS para correr el carrusel: estos tests cuidan, en la
página que sirve la vista, que no se vuelva a llamar a destroy() y que el carrusel viejo
se frene y salga entero de la página antes de armar el nuevo.
"""
import re

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase, override_settings

from forms_builder.forms.models import Form

from catus.tests.factories import make_animal, make_user
from catus.views.adoption import PreAdoptionPerrosView, PreAdoptionView

MOSTRAR_FOTOS = re.compile(r"function showAnimalPhotos\(isDog, animalId\) \{.*?\n    \}\n", re.S)


@override_settings(ENV="TEST")
class CarruselDeFotosTest(TestCase):

    def setUp(self):
        rescatista = make_user(email="rescatista@catpuccino.test")
        self.paginas = [
            (PreAdoptionView, make_animal(nombre="Michi", tipo="G", cargado_por=rescatista)),
            (PreAdoptionPerrosView, make_animal(nombre="Firulais", tipo="P", cargado_por=rescatista)),
        ]
        Form.objects.create(title="Pre adopción", slug=PreAdoptionView.form_slug)
        Form.objects.create(title="Pre adopción perros", slug=PreAdoptionPerrosView.form_slug)

    def mostrar_fotos(self, vista, animal):
        """El código de showAnimalPhotos() tal como sale en la página, sin los comentarios."""

        request = RequestFactory().get("/pre-adopcion/", {"id": animal.id})
        request.user = AnonymousUser()

        response = vista.as_view()(request)
        response.render()
        self.assertEqual(response.status_code, 200)

        funcion = MOSTRAR_FOTOS.search(response.content.decode())
        self.assertIsNotNone(funcion, "no está showAnimalPhotos() en la página")

        return "\n".join(linea for linea in funcion.group(0).splitlines() if not linea.strip().startswith("//"))

    def test_no_destruye_el_carrusel_viejo(self):

        for vista, animal in self.paginas:
            with self.subTest(animal=vista.animal_type):
                codigo = self.mostrar_fotos(vista, animal)

                self.assertNotRegex(codigo, r"\.destroy\(",
                                    "destroy() deja en null lo que usa el reacomodo pendiente del loop")

    def test_frena_el_carrusel_viejo_y_lo_saca_entero_antes_de_armar_el_nuevo(self):
        """Sin destroy(), el carrusel viejo sigue vivo: si no se frena, su autoplay sigue
        corriendo para siempre sobre nodos sueltos, y si quedan los envoltorios que le
        agrega lightSlider, el nuevo se arma adentro del viejo, con las flechas y el
        paginador repetidos."""

        for vista, animal in self.paginas:
            with self.subTest(animal=vista.animal_type):
                codigo = self.mostrar_fotos(vista, animal)

                self.assertIn("slider.pause()", codigo)
                self.assertIn('slider.closest(".lSSlideOuter").remove()', codigo)

                self.assertLess(codigo.index("slider.pause()"), codigo.index(".lightSlider("))
                self.assertLess(codigo.index('slider.closest(".lSSlideOuter").remove()'), codigo.index("response.html"))

    def test_una_respuesta_vieja_no_pisa_a_la_nueva(self):
        """Cambiando rápido el desplegable, las respuestas de /animal/photos/ pueden llegar
        en otro orden: la del animal anterior pisaba a la del elegido."""

        for vista, animal in self.paginas:
            with self.subTest(animal=vista.animal_type):
                codigo = self.mostrar_fotos(vista, animal)

                self.assertIn("var pedido = ++pedidosDeFotos", codigo)
                self.assertIn("if (pedido !== pedidosDeFotos)", codigo)
                self.assertLess(codigo.index("if (pedido !== pedidosDeFotos)"), codigo.index("response.html"))

    def test_al_mostrar_el_formulario_pide_las_fotos_del_animal_elegido(self):
        """showForm() pedía siempre las fotos del animal de la URL (o de ninguno): al tocar
        "Aceptar y Completar el Formulario" el carrusel mostraba otro animal que el que la
        persona había elegido en el desplegable, o desaparecía."""

        for vista, animal in self.paginas:
            with self.subTest(animal=vista.animal_type):
                request = RequestFactory().get("/pre-adopcion/", {"id": animal.id})
                request.user = AnonymousUser()
                response = vista.as_view()(request)
                response.render()

                mostrar = re.search(r"function showForm\(\) \{.*?\n    \}\n", response.content.decode(), re.S).group(0)
                codigo = "\n".join(l for l in mostrar.splitlines() if not l.strip().startswith("//"))

                self.assertIn("showAnimalPhotos(isDog, fotosDe)", codigo)
                self.assertNotIn('showAnimalPhotos(isDog, "{}")'.format(animal.id), codigo)
