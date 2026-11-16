"""El aviso "ya encontró familia" lo elige el rescatista, en cada lugar donde marca "Adoptado".

Marcar un animal adoptado puede terminar en mails a todos los que se postularon
(services/aviso_candidatos.py), y un cambio de estado puede ser un error. Por eso, en el botón
"Adoptó" del formulario, en "¿Quién lo adoptó?" del panel, en el selector de la edición y en
"Ya se adoptó" del mail de expiración, el rescatista ve a cuántos se les avisaría y una casilla
marcada de entrada. Lo que elige queda en Animal.avisar_candidatos; sin elección no se avisa.
"""
from catus.models import Animal
from catus.services import aviso_candidatos, estados, expiracion
from catus.tests.factories import make_animal, make_estado_formulario, make_user
from catus.tests.test_estados import EstadosTestCase, hace


class AvisoOpcionalBase(EstadosTestCase):

    def candidatos(self, animal, cuantos):
        return [make_estado_formulario(animal, persona_nombre="Persona {}".format(i), tipo="A", hash="h-{}-{}".format(animal.id, i))
                for i in range(cuantos)]


class BotonAdoptoDelFormularioTest(AvisoOpcionalBase):

    def test_adopto_lleva_a_un_paso_que_dice_a_cuantos_se_les_avisaria(self):
        animal = self.animal(nombre="Michi")
        ana, *otros = self.candidatos(animal, 3)

        html = self.client.get("/formularios/{}/".format(ana.hash)).content.decode()
        self.assertIn('href="?confirmar=adopcion#titulo-estado"', html)

        html = self.client.get("/formularios/{}/?confirmar=adopcion".format(ana.hash)).content.decode()
        self.assertIn("las otras 2 personas que se postularon", html)
        self.assertIn('name="avisar_candidatos" value="1" checked', html)
        animal.refresh_from_db()
        self.assertEqual(animal.estado, "D", "mirar el paso no cambia nada")

    def test_con_la_casilla_marcada_queda_elegido_avisar(self):
        animal = self.animal(nombre="Michi")
        ana, _ = self.candidatos(animal, 2)
        self.client.post("/formularios/{}/".format(ana.hash), {"estado": "A", "volver": "1", "confirmo_adopcion": "1", "avisar_candidatos": "1"})
        animal.refresh_from_db()
        self.assertEqual((animal.estado, animal.avisar_candidatos), ("A", True))

    def test_sin_la_casilla_no_se_avisa(self):
        animal = self.animal(nombre="Michi")
        ana, _ = self.candidatos(animal, 2)
        self.client.post("/formularios/{}/".format(ana.hash), {"estado": "A", "volver": "1", "confirmo_adopcion": "1"})
        animal.refresh_from_db()
        self.assertEqual((animal.estado, animal.avisar_candidatos), ("A", False))

    def test_si_nadie_mas_se_postulo_no_hay_casilla(self):
        animal = self.animal(nombre="Michi")
        ana, = self.candidatos(animal, 1)
        html = self.client.get("/formularios/{}/?confirmar=adopcion".format(ana.hash)).content.decode()
        self.assertIn("Sí, adoptó", html)
        self.assertNotIn('name="avisar_candidatos"', html)


class DialogoDelPanelTest(AvisoOpcionalBase):

    def test_el_panel_sabe_a_quienes_avisaria(self):
        animal = self.animal(nombre="Michi")
        formularios = self.candidatos(animal, 2)
        self.assertEqual(sorted(self.client.get("/accounts/profile/").context["avisables_json"][str(animal.id)]),
                         sorted(f.id for f in formularios))

    def test_la_casilla_del_dialogo_llega_a_la_vista(self):
        for valor, esperado in (("1", True), ("0", False), (None, None)):
            with self.subTest(valor=valor):
                animal = self.animal(nombre="Michi {}".format(valor))
                datos = {} if valor is None else {"avisar_candidatos": valor}
                animal = self.boton("/animal/marcaradoptado/", animal, **datos)
                self.assertEqual((animal.estado, animal.avisar_candidatos), ("A", esperado))


class SelectorDeLaEdicionTest(AvisoOpcionalBase):

    def test_la_edicion_muestra_la_casilla_si_alguien_se_postulo(self):
        animal = self.animal(nombre="Michi")
        self.candidatos(animal, 2)
        html = self.client.get("/animales/{}/".format(animal.id)).content.decode()
        self.assertIn('id="aviso-candidatos-edicion"', html)
        self.assertIn("las 2 personas que se postularon", html)

    def test_lo_que_elige_al_guardar(self):
        casos = (({"aviso_candidatos_mostrado": "1", "avisar_candidatos": "1"}, True),
                 ({"aviso_candidatos_mostrado": "1"}, False),
                 ({}, None))
        for extra, esperado in casos:
            with self.subTest(extra=extra):
                animal = self.animal(nombre="Michi")
                animal = self.editar(animal, estado="A", **extra)
                self.assertEqual((animal.estado, animal.avisar_candidatos), ("A", esperado))


class MailDeExpiracionTest(AvisoOpcionalBase):

    def expirado(self):
        animal = self.animal(nombre="Willy", estado="E", expiro_el=hace(1))
        return animal

    def test_ya_se_adopto_trae_la_casilla_y_respeta_lo_elegido(self):
        for datos, esperado in (({"avisar_candidatos": "1"}, True), ({}, False)):
            with self.subTest(datos=datos):
                animal = self.expirado()
                url = expiracion.link(animal, expiracion.ADOPTADO)
                self.client.logout()
                self.assertIn('name="avisar_candidatos"', self.client.get(url).content.decode())
                self.client.post(url, dict(respuesta=expiracion.ADOPTADO, **datos))
                animal.refresh_from_db()
                self.assertEqual((animal.estado, animal.avisar_candidatos), ("A", esperado))
                self.client.force_login(self.rescatista)


class EleccionYEstadosTest(AvisoOpcionalBase):

    def test_volver_a_en_adopcion_borra_la_eleccion(self):
        animal = self.animal(nombre="Michi")
        estados.marcar_adoptado(animal, avisar=True)
        estados.republicar(animal)
        animal.refresh_from_db()
        self.assertIsNone(animal.avisar_candidatos)

    def test_volver_a_marcar_sin_preguntar_no_pisa_lo_elegido(self):
        """"¿Quién lo adoptó?" sobre un animal ya adoptado, sin la casilla (no hay nadie más):
        se queda con lo que eligió antes."""
        animal = self.animal(nombre="Michi")
        estados.marcar_adoptado(animal, avisar=True)
        estados.marcar_adoptado(animal)
        animal.refresh_from_db()
        self.assertTrue(animal.avisar_candidatos)

    def test_candidatos_cuenta_sin_el_de_quien_adopto(self):
        animal = self.animal(nombre="Michi")
        ana, *otros = self.candidatos(animal, 3)
        self.assertEqual(aviso_candidatos.candidatos(animal), 3)
        self.assertEqual(aviso_candidatos.candidatos(animal, sin=ana.id), 2)
