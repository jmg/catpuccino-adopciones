"""Tests de las vistas de usuario: el perfil público /<handle>/ y /usuario/save/."""
import datetime

from django.test import TestCase
from django.utils import timezone

from catus.tests.factories import make_animal, make_user


class PerfilConHandleRepetidoTest(TestCase):
    """En producción quedaron 8 handles repetidos, de antes de que se validaran.

    El perfil buscaba con get_object_or_404(CatusUser, handle=...), que con dos filas
    tira MultipleObjectsReturned: /<handle>/ daba 500 para todas las cuentas que lo
    compartían, justo el link que se manda en el mail de aprobación.
    """

    def perfil(self, handle):

        return self.client.get("/{}/".format(handle))

    def test_handle_unico_sigue_mostrando_esa_cuenta(self):

        refugio = make_user(email="refugio@test.com", handle="refugio")
        make_animal(nombre="Willy", cargado_por=refugio)

        response = self.perfil("refugio")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["user"], refugio)
        self.assertContains(response, "Willy")

    def test_handle_desconocido_es_404(self):

        make_user(email="refugio@test.com", handle="refugio")

        self.assertEqual(self.perfil("nadie").status_code, 404)

    def test_handle_repetido_no_da_500(self):

        make_user(email="a@test.com", handle="refugio")
        make_user(email="b@test.com", handle="refugio")

        self.assertEqual(self.perfil("refugio").status_code, 200)

    def test_gana_la_que_tiene_animales_en_adopcion(self):
        """La cuenta vieja tiene más animales, pero ninguno se ve: ya están adoptados."""

        vieja = make_user(email="vieja@test.com", handle="refugio")
        make_animal(nombre="Tom", cargado_por=vieja, estado="A")
        make_animal(nombre="Jerry", cargado_por=vieja, estado="A")
        make_animal(nombre="Garfield", cargado_por=vieja, aprobado=False)

        activa = make_user(email="activa@test.com", handle="refugio")
        make_animal(nombre="Willy", cargado_por=activa)

        response = self.perfil("refugio")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["user"], activa)
        self.assertContains(response, "Willy")

    def test_gana_la_que_tiene_mas_animales_en_adopcion(self):

        una = make_user(email="una@test.com", handle="refugio")
        make_animal(nombre="Willy", cargado_por=una)

        dos = make_user(email="dos@test.com", handle="refugio")
        make_animal(nombre="Tom", cargado_por=dos)
        make_animal(nombre="Jerry", cargado_por=dos)

        self.assertEqual(self.perfil("refugio").context["user"], dos)

    def test_sin_animales_en_adopcion_gana_la_que_mas_cargo(self):

        make_user(email="vacia@test.com", handle="refugio")
        con_historia = make_user(email="historia@test.com", handle="refugio")
        make_animal(nombre="Tom", cargado_por=con_historia, estado="A")

        self.assertEqual(self.perfil("refugio").context["user"], con_historia)

    def test_empatadas_gana_la_que_entro_mas_recientemente(self):

        ahora = timezone.now()
        make_user(email="antes@test.com", handle="refugio", last_login=ahora - datetime.timedelta(days=300))
        reciente = make_user(email="reciente@test.com", handle="refugio", last_login=ahora)
        make_user(email="nunca@test.com", handle="refugio", last_login=None)

        self.assertEqual(self.perfil("refugio").context["user"], reciente)

    def test_empate_total_gana_la_cuenta_mas_vieja(self):
        """Siempre la misma, no la que devuelva la base esa vez."""

        primera = make_user(email="primera@test.com", handle="refugio")
        make_user(email="segunda@test.com", handle="refugio")
        make_user(email="tercera@test.com", handle="refugio")

        for _ in range(3):
            self.assertEqual(self.perfil("refugio").context["user"], primera)

    def test_no_mezcla_los_animales_de_las_cuentas_repetidas(self):

        una = make_user(email="una@test.com", handle="refugio")
        make_animal(nombre="Tom", cargado_por=una)
        make_animal(nombre="Jerry", cargado_por=una)

        otra = make_user(email="otra@test.com", handle="refugio")
        make_animal(nombre="Willy", cargado_por=otra)

        response = self.perfil("refugio")

        self.assertContains(response, "Tom")
        self.assertNotContains(response, "Willy")

    def test_el_perfil_por_id_sigue_andando_para_la_que_no_gana(self):
        """La otra cuenta tiene su página en /usuario/<id>/animales/, que no usa el handle."""

        una = make_user(email="una@test.com", handle="refugio")
        make_animal(nombre="Tom", cargado_por=una)
        make_animal(nombre="Jerry", cargado_por=una)

        otra = make_user(email="otra@test.com", handle="refugio")
        make_animal(nombre="Willy", cargado_por=otra)

        self.assertEqual(self.perfil("refugio").context["user"], una)

        response = self.client.get("/usuario/{}/animales/".format(otra.id))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["user"], otra)
        self.assertContains(response, "Willy")


class SaveViewTest(TestCase):
    """/usuario/save/ es el destino del form de perfil: solo recibe POST."""

    def datos(self, **cambios):

        datos = {
            "handle": "refugio", "email": "refugio@test.com", "title": "Refugio",
            "description": "", "facebook": "", "twitter": "", "instagram": "",
        }
        datos.update(cambios)
        return datos

    def test_get_es_405_y_no_500(self):
        """SaveView solo define post(), pero es un TemplateView: con GET buscaba el
        template usuario/save.html, que no existe, y daba 500."""

        response = self.client.get("/usuario/save/")

        self.assertEqual(response.status_code, 405)
        self.assertEqual(response["Allow"], "POST")

    def test_get_logueado_tambien_es_405(self):

        self.client.force_login(make_user(email="refugio@test.com"))

        self.assertEqual(self.client.get("/usuario/save/").status_code, 405)

    def test_post_guarda_el_perfil_y_vuelve_al_perfil(self):

        yo = make_user(email="refugio@test.com")
        self.client.force_login(yo)

        response = self.client.post("/usuario/save/", self.datos(title="Refugio Villa Crespo"))

        self.assertRedirects(response, "/accounts/profile/", fetch_redirect_response=False)
        yo.refresh_from_db()
        self.assertEqual(yo.title, "Refugio Villa Crespo")
        self.assertEqual(yo.handle, "refugio")
        self.assertTrue(self.client.session.get("usuario_save_success"))

    def test_post_invalido_no_guarda_y_deja_el_error(self):

        make_user(email="otra@test.com", handle="refugio")
        yo = make_user(email="yo@test.com", handle="yo")
        self.client.force_login(yo)

        response = self.client.post("/usuario/save/", self.datos(email="yo@test.com"))

        self.assertRedirects(response, "/accounts/profile/", fetch_redirect_response=False)
        yo.refresh_from_db()
        self.assertEqual(yo.handle, "yo")
        self.assertIn("handle", self.client.session.get("usuario_save_error", ""))


class SaveViewSinLoginTest(TestCase):

    def test_un_post_anonimo_va_al_login_y_no_da_500(self):
        """Armaba el form con AnonymousUser como instancia y daba 500."""

        response = self.client.post("/usuario/save/", {"handle": "x", "email": "x@test.com"})

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])
        #con next=/usuario/save/, después del login caía en un GET que da 405
        self.assertNotIn("next=", response["Location"])


class AnimalesPorIdTest(TestCase):

    def test_un_id_que_no_es_un_numero_es_404_y_no_500(self):
        """Con url .+ un id de texto llegaba a get_object_or_404 y daba ValueError."""

        self.assertEqual(self.client.get("/usuario/abc/animales/").status_code, 404)

    def test_un_id_numerico_sigue_andando(self):

        rescatista = make_user(email="porid@catpuccino.test")

        self.assertEqual(self.client.get("/usuario/{}/animales/".format(rescatista.id)).status_code, 200)
