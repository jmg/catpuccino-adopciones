"""El panel de cada cuenta: /accounts/profile/, a donde manda el login.

Para el equipo lista todos los formularios de la historia, que en producción son miles, y
esa pantalla tardaba 15 segundos y pesaba 8 MB: cada fila pedía su gato con una consulta
aparte, y la sangría del template era la mitad de cada fila. Va por el cliente de test
porque lo que importa es la página entera, con el login y los templates de verdad.
"""
import uuid

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from catus.models import Animal, AnimalImage, EstadoFormulario
from catus.tests.factories import make_animal, make_estado_formulario, make_user


def poblar(equipo, rescatistas, animales, formularios_por_animal, prefijo):
    """Animales repartidos entre el equipo y los rescatistas, con dos fotos y sus formularios.

    Va con bulk_create: con make_animal cada alta dispara las señales que reescriben el
    desplegable del formulario público, y miles de altas tardarían minutos.
    """

    ahora = timezone.now()
    duenios = [equipo] + rescatistas

    Animal.objects.bulk_create([
        Animal(nombre="{}{}".format(prefijo, i), estado="DRAE"[i % 4], aprobado=bool(i % 3), tipo="GP"[i % 2],
               cargado_por=duenios[i % len(duenios)], fecha_ingreso=ahora, datos="Muy mimoso. " * 40)
        for i in range(animales)
    ])
    creados = list(Animal.objects.filter(nombre__startswith=prefijo))

    AnimalImage.objects.bulk_create([
        AnimalImage(animal=animal, image="gallery/{}-{}.jpeg".format(animal.pk, n)) for animal in creados for n in range(2)
    ])
    EstadoFormulario.objects.bulk_create([
        EstadoFormulario(gato=animal, hash=str(uuid.uuid4()), persona_nombre="Candidata {} de {}".format(n, animal.nombre),
                         fecha_ingreso=ahora)
        for animal in creados for n in range(formularios_por_animal)
    ])


class PerfilDelEquipoTest(TestCase):

    def setUp(self):
        self.equipo = make_user(email="equipo@catpuccino.test", is_superuser=True, is_staff=True)
        self.rescatistas = [make_user(email="rescatista{}@catpuccino.test".format(i), handle="rescatista{}".format(i))
                            for i in range(20)]

    def abrir(self, user):

        self.client.force_login(user)
        with CaptureQueriesContext(connection) as consultas:
            response = self.client.get("/accounts/profile/")

        self.assertEqual(response.status_code, 200)
        return response, consultas

    def test_no_hace_una_consulta_por_formulario(self):
        """Cada fila de la pestaña Formularios muestra el nombre del gato, y lo traía con
        una consulta propia: con los miles de formularios que ve el equipo eran miles de
        consultas, y por eso el perfil tardaba 15 segundos. Con 400 animales y 1200
        formularios, la página tiene que costar lo mismo que con un puñado."""

        poblar(self.equipo, self.rescatistas, animales=7, formularios_por_animal=1, prefijo="Pocos")
        _, con_pocos = self.abrir(self.equipo)

        poblar(self.equipo, self.rescatistas, animales=400, formularios_por_animal=3, prefijo="Muchos")
        response, con_muchos = self.abrir(self.equipo)

        #que la tabla esté entera: un perfil que no lista nada también hace pocas consultas
        cuerpo = response.content.decode()
        self.assertEqual(cuerpo.count('/contrato/" class="action-btn"'), EstadoFormulario.objects.count())
        self.assertIn("Muchos399", cuerpo)

        self.assertEqual(len(con_muchos), len(con_pocos), "el perfil hace una consulta por fila")
        self.assertLessEqual(len(con_muchos), 6)

    def test_la_fila_de_un_formulario_no_lleva_la_sangria_del_template(self):
        """La página pesaba 8 MB: la sangría del template era más de la mitad de cada fila
        (unos 1300 bytes por formulario), multiplicada por todos los formularios de la historia."""

        self.client.force_login(self.equipo)
        vacio = len(self.client.get("/accounts/profile/").content)

        animal = make_animal(nombre="Willy", cargado_por=self.rescatistas[0])
        for n in range(50):
            make_estado_formulario(animal=animal, hash=str(uuid.uuid4()), persona_nombre="Candidata {}".format(n))

        por_fila = (len(self.client.get("/accounts/profile/").content) - vacio) / 50

        self.assertLess(por_fila, 800)

    def test_cada_fila_trae_el_candidato_el_animal_y_sus_links(self):
        """El only() de la consulta trae sólo lo que muestra la fila: que no falte nada."""

        animal = make_animal(nombre="Willy", cargado_por=self.rescatistas[0])
        estado_form = make_estado_formulario(animal=animal, hash="abc-123", persona_nombre="Ana Pérez")

        cuerpo = self.abrir(self.equipo)[0].content.decode()

        self.assertIn('href="/formularios/abc-123/">Ana Pérez</a>', cuerpo)
        self.assertRegex(cuerpo, r'<div class="limited-td">\s*Willy\s*</div>')
        self.assertIn('href="/formulario/{}/contrato/"'.format(estado_form.id), cuerpo)

    def test_un_formulario_sin_animal_no_rompe_la_tabla(self):
        """gato es SET_NULL: borrar un animal deja sus formularios sin gato, y el equipo
        los sigue viendo."""

        make_estado_formulario(animal=None, hash="huerfano", persona_nombre="Sin Gato")

        cuerpo = self.abrir(self.equipo)[0].content.decode()

        self.assertIn('href="/formularios/huerfano/">Sin Gato</a>', cuerpo)

    def test_el_rescatista_ve_solo_los_formularios_de_sus_animales(self):

        mio = make_animal(nombre="Willy", cargado_por=self.rescatistas[0])
        ajeno = make_animal(nombre="Garfield", cargado_por=self.rescatistas[1])
        make_estado_formulario(animal=mio, hash="mio", persona_nombre="Para Mi")
        make_estado_formulario(animal=ajeno, hash="ajeno", persona_nombre="Para Otro")

        cuerpo = self.abrir(self.rescatistas[0])[0].content.decode()

        self.assertIn("/formularios/mio/", cuerpo)
        self.assertNotIn("/formularios/ajeno/", cuerpo)


class TooltipsDelPerfilTest(TestCase):

    def test_los_tooltips_se_crean_al_pasar_el_mouse_y_no_todos_al_cargar(self):
        """Con miles de botones, crear un tooltip por botón al cargar (dos en los de
        acción) congelaba la página varios segundos, y se veían dos tooltips encimados."""

        equipo = make_user(email="equipo-tips@catpuccino.test", is_superuser=True, is_staff=True)
        self.client.force_login(equipo)

        html = self.client.get("/accounts/profile/").content.decode()

        import re

        self.assertIn("tippy.delegate(", html)
        #la única llamada directa que queda es el aviso de "link copiado", sobre un div
        self.assertIsNone(re.search(r"""tippy\(\s*['"]""", html), "volvió una llamada a tippy() sobre todos los botones")
        self.assertIn("tippy.js@6.3.7", html, "la versión de tippy tiene que ser fija: delegate y el resto dependen de ella")
