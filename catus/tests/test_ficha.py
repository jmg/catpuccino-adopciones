"""La ficha pública de cada animal, /adoptar/<id>-<nombre>/ (views/ficha.py).

Antes no existía: el nombre y el botón de la tarjeta llevaban al formulario, y un link
compartido por WhatsApp mostraba la portada (og:url fijo en "/", sin foto), así que nadie
podía mandarle a otra persona "mirá a este gato". Estos tests cuidan que la ficha exista
solo para los aprobados, que la URL se pueda compartir aunque cambie el nombre, que lo que
ven WhatsApp y Google sea el animal, y que la descripción —que la escribe cualquiera que se
registra— no pueda meter HTML en la página ni en las meta.
"""
import re
from urllib.parse import quote

from django.test import SimpleTestCase, TestCase

from catus.models import Animal
from catus.services import ficha
from catus.tests.factories import make_animal, make_animal_image, make_user

HOST = "https://adopciones.catpuccino.org"


def meta(response, nombre):
    """El content de <meta name=… > o <meta property=… >, o None."""

    html = response.content.decode()
    encontrada = re.search(r'<meta (?:name|property)="{}" content="([^"]*)"'.format(re.escape(nombre)), html)
    return encontrada.group(1) if encontrada else None


class FichaTest(TestCase):

    def setUp(self):

        self.rescatista = make_user(email="refugio@test.com", handle="refugio", title="Refugio Patitas", instagram="patitas")
        self.michi = make_animal(
            nombre="Michi", sexo="H", edad="2 meses", zona="Lanús", cargado_por=self.rescatista,
            datos="<p>Muy <b>mimosa</b> y juguetona.</p>",
        )

    def ficha(self, animal=None):

        return self.client.get((animal or self.michi).get_ficha_url())

    def test_un_animal_en_adopcion_tiene_su_pagina(self):

        response = self.ficha()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<h1 class="ficha-nombre">Michi</h1>', html=True)
        self.assertContains(response, "Muy <b>mimosa</b> y juguetona.")
        self.assertContains(response, "Lanús")
        self.assertContains(response, "2 meses")

    def test_la_url_lleva_el_nombre_sin_tildes(self):

        animal = make_animal(nombre="Ñandú Pérez")

        self.assertEqual(animal.get_ficha_url(), "/adoptar/{}-nandu-perez/".format(animal.id))

    def test_un_nombre_sin_letras_queda_solo_con_el_id(self):

        animal = make_animal(nombre="🐱🐱")

        self.assertEqual(animal.get_ficha_url(), "/adoptar/{}/".format(animal.id))
        self.assertEqual(self.ficha(animal).status_code, 200)

    def test_el_boton_va_al_formulario_de_su_especie(self):
        """Igual que el botón de la tarjeta: gatos y perros tienen formularios distintos."""

        perro = make_animal(nombre="Firulais", tipo="P")

        self.assertContains(self.ficha(), 'href="/pre-adopcion/?id={}"'.format(self.michi.id))
        self.assertContains(self.ficha(), "Quiero adoptar a Michi")
        self.assertContains(self.ficha(perro), 'href="/pre-adopcion/perros/?id={}"'.format(perro.id))

    def test_un_link_propio_del_animal_gana_como_en_la_tarjeta(self):

        animal = make_animal(nombre="Tom", custom_link="https://ejemplo.test/adoptar")

        self.assertContains(self.ficha(animal), 'href="https://ejemplo.test/adoptar"')

    def test_con_otro_nombre_redirige_a_la_url_de_ahora(self):
        """El link compartido sigue andando si después le cambian el nombre."""

        canonica = self.michi.get_ficha_url()

        for ruta in ["/adoptar/{}-otro-nombre/", "/adoptar/{}/", "/adoptar/{}-michi", "/adoptar/{}-MICHI/"]:
            with self.subTest(ruta=ruta):
                response = self.client.get(ruta.format(self.michi.id))
                self.assertEqual(response.status_code, 301)
                self.assertEqual(response["Location"], canonica)

    def test_la_redireccion_conserva_el_resto_del_link(self):

        response = self.client.get("/adoptar/{}/?fbclid=abc&utm_source=ig".format(self.michi.id))

        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], self.michi.get_ficha_url() + "?fbclid=abc&utm_source=ig")

    def test_sin_aprobar_no_existe(self):
        """Lo que todavía no aprobó nadie no se ve en ningún lado, tampoco acá."""

        borrador = make_animal(nombre="Borrador", aprobado=False)

        self.assertEqual(self.ficha(borrador).status_code, 404)
        self.assertEqual(self.client.get("/adoptar/{}-borrador/".format(borrador.id)).status_code, 404)

    def test_un_id_que_no_existe_es_404(self):

        self.assertEqual(self.client.get("/adoptar/999999-nadie/").status_code, 404)
        self.assertEqual(self.client.get("/adoptar/99999999999999999999-nadie/").status_code, 404)

    def test_lo_que_ven_whatsapp_y_google_es_el_animal(self):

        response = self.ficha()
        url = HOST + self.michi.get_ficha_url()

        self.assertContains(response, '<link rel="canonical" href="{}">'.format(url))
        self.assertEqual(meta(response, "og:url"), url)
        self.assertEqual(meta(response, "og:title"), "Michi, gata en adopción en Lanús")
        self.assertContains(response, "<title>Michi, gata en adopción en Lanús | Catpuccino Adopciones</title>")
        self.assertTrue(meta(response, "description").startswith("Michi busca familia: gata, 2 meses, en Lanús. Muy mimosa"))
        self.assertEqual(meta(response, "og:description"), meta(response, "description"))
        self.assertIsNone(meta(response, "robots"))

    def test_la_foto_para_compartir_es_absoluta_y_prefiere_la_de_instagram(self):

        foto = make_animal_image(self.michi)

        self.assertEqual(meta(self.ficha(), "og:image"), HOST + foto.image.url)
        self.assertEqual(meta(self.ficha(), "twitter:card"), "summary_large_image")

        foto.image_for_instagram = "gallery/posteo.jpeg"
        foto.save()

        self.assertEqual(meta(self.ficha(), "og:image"), HOST + "/gallery/posteo.jpeg")

    def test_sin_fotos_no_hay_og_image(self):

        response = self.ficha()

        self.assertIsNone(meta(response, "og:image"))
        self.assertEqual(meta(response, "twitter:card"), "summary")

    def test_la_descripcion_no_mete_html_ni_en_la_pagina_ni_en_las_meta(self):

        self.michi.datos = '<script>alert(1)</script><img src=x onerror="alert(2)"><p>Hola &amp; chau</p>"><b>'
        self.michi.save()

        response = self.ficha()
        html = response.content.decode()

        self.assertNotIn("<script>alert", html)
        self.assertNotIn("onerror", html)
        descripcion = meta(response, "description")
        self.assertNotIn("<", descripcion)
        #la entidad se lee como "&", y el atributo la vuelve a escapar una sola vez
        self.assertIn("Hola &amp; chau", descripcion)
        self.assertNotIn("&amp;amp;", html.split("<title>")[0])

    def test_el_nombre_tampoco_mete_html(self):

        animal = make_animal(nombre='<img src=x onerror="alert(1)">')

        html = self.ficha(animal).content.decode()

        self.assertNotIn('<img src=x onerror', html)

    def test_dice_quien_lo_rescato_y_lleva_a_su_perfil(self):

        response = self.ficha()

        self.assertContains(response, 'href="/refugio/"')
        self.assertContains(response, "Refugio Patitas")
        self.assertContains(response, "Rescatada por")
        self.assertContains(response, 'href="https://www.instagram.com/patitas"')

    def test_si_el_handle_es_de_dos_cuentas_lleva_al_perfil_por_id(self):
        """/<handle>/ muestra una sola de las cuentas que lo comparten."""

        otra = make_user(email="otra@test.com", handle="refugio")
        animal = make_animal(nombre="Tom", cargado_por=otra)

        self.assertContains(self.ficha(animal), 'href="/usuario/{}/animales/"'.format(otra.id))

    def test_se_comparte_por_whatsapp_o_copiando_el_link(self):

        response = self.ficha()
        url = HOST + self.michi.get_ficha_url()

        self.assertContains(response, "https://wa.me/?text=" + quote("Mirá a Michi, gata en adopción: " + url, safe=""))
        self.assertContains(response, 'data-url="{}"'.format(url))

    def test_las_fotos_se_centran_en_el_recorte_elegido(self):

        foto = make_animal_image(self.michi, size=(1600, 1200))
        foto.set_crop((0.25, 0.0, 0.75, 1.0))
        foto.save()

        self.assertContains(self.ficha(), 'style="object-position: 100.0% 50.0%"')


class FichaNoDisponibleTest(TestCase):
    """Un link viejo a un animal que ya no está en adopción no da error: lo dice con calma
    y ofrece otros de la misma especie, sin formulario."""

    def setUp(self):

        self.gato = make_animal(nombre="Pelusa", sexo="H", estado="R")
        self.otro_gato = make_animal(nombre="Garfield")
        self.perro = make_animal(nombre="Firulais", tipo="P")

    def test_reservado(self):

        response = self.client.get(self.gato.get_ficha_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pelusa ya no está en adopción")
        self.assertContains(response, "Está reservada")
        self.assertNotContains(response, "/pre-adopcion/?id=")
        self.assertNotContains(response, "Quiero adoptar")
        self.assertNotContains(response, "wa.me")

    def test_muestra_otros_de_la_misma_especie_en_adopcion(self):

        make_animal(nombre="Adoptado", estado="A")
        make_animal(nombre="Sin aprobar", aprobado=False)

        response = self.client.get(self.gato.get_ficha_url())

        self.assertContains(response, 'href="{}"'.format(self.otro_gato.get_ficha_url()))
        self.assertNotContains(response, self.perro.get_ficha_url())
        self.assertNotContains(response, "Sin aprobar")
        self.assertNotContains(response, ">Adoptado<")
        self.assertContains(response, 'href="/?tipo=gatos"')

    def test_adoptado(self):

        self.gato.estado = "A"
        self.gato.save()

        self.assertContains(self.client.get(self.gato.get_ficha_url()), "Ya encontró una familia")

    def test_una_camada_concuerda_en_plural(self):

        camada = make_animal(nombre="Tom y Jerry", sexo="A", estado="R")

        response = self.client.get(camada.get_ficha_url())

        self.assertContains(response, "Tom y Jerry ya no están en adopción")
        self.assertContains(response, "Están reservados")

    def test_no_se_indexa(self):

        response = self.client.get(self.gato.get_ficha_url())

        self.assertEqual(meta(response, "robots"), "noindex")
        self.assertEqual(meta(response, "og:title"), "Pelusa")


class FichaTextosTest(SimpleTestCase):
    """Los textos de services/ficha.py, que no necesitan base."""

    def animal(self, **datos):

        datos.setdefault("nombre", "Michi")
        datos.setdefault("tipo", "G")
        datos.setdefault("sexo", "M")
        datos.setdefault("estado", "D")
        return Animal(**datos)

    def test_especie_segun_tipo_y_sexo(self):

        casos = [("G", "M", "gato"), ("G", "H", "gata"), ("G", "A", "gatos"), ("G", "D", "gato"),
                 ("P", "M", "perro"), ("P", "H", "perra"), ("P", "A", "perros")]
        for tipo, sexo, esperada in casos:
            with self.subTest(tipo=tipo, sexo=sexo):
                self.assertEqual(ficha.especie(self.animal(tipo=tipo, sexo=sexo)), esperada)

    def test_titulo(self):

        self.assertEqual(ficha.titulo_de_la_ficha(self.animal(zona=" Lanús ")), "Michi, gato en adopción en Lanús")
        self.assertEqual(ficha.titulo_de_la_ficha(self.animal(zona=None)), "Michi, gato en adopción")
        self.assertEqual(ficha.titulo_de_la_ficha(self.animal(estado="A")), "Michi")

    def test_la_descripcion_no_pasa_de_160_y_corta_en_una_palabra(self):

        animal = self.animal(edad="1 año", datos="<p>" + "palabra " * 100 + "</p>")

        descripcion = ficha.descripcion_de_la_ficha(animal)

        self.assertLessEqual(len(descripcion), 160)
        self.assertTrue(descripcion.endswith("palabra…"))
        self.assertTrue(descripcion.startswith("Michi busca familia: gato, 1 año. palabra"))

    def test_la_descripcion_de_una_camada(self):

        animal = self.animal(nombre="Tom y Jerry", sexo="A", datos="")

        self.assertEqual(ficha.descripcion_de_la_ficha(animal), "Tom y Jerry buscan familia: gatos.")

    def test_texto_para_meta_saca_las_etiquetas_y_las_entidades(self):

        self.assertEqual(ficha.texto_para_meta("<p>Hola &amp;\n\n <b>chau</b></p>"), "Hola & chau")
        self.assertEqual(ficha.texto_para_meta(None), "")

    def test_posicion_del_recorte(self):
        """El recorte es cuadrado: en una apaisada de 4:3 ocupa 0,75 del ancho."""

        self.assertEqual(ficha.posicion_del_recorte((0.0, 0.0, 0.75, 1.0)), "0.0% 50.0%")
        self.assertEqual(ficha.posicion_del_recorte((0.25, 0.0, 0.75, 1.0)), "100.0% 50.0%")
        self.assertEqual(ficha.posicion_del_recorte((0.125, 0.0, 0.75, 1.0)), "50.0% 50.0%")
        #una vertical de 3:4, con el recorte abajo de todo
        self.assertEqual(ficha.posicion_del_recorte((0.0, 0.25, 1.0, 0.75)), "50.0% 100.0%")
        #un recorte chico, a la izquierda: igual se ve todo el alto
        self.assertEqual(ficha.posicion_del_recorte((0.1, 0.3, 0.3, 0.4)), "0.0% 50.0%")
        #en una foto cuadrada se ve entera: no hace falta
        self.assertIsNone(ficha.posicion_del_recorte((0.2, 0.2, 0.5, 0.5)))
        self.assertIsNone(ficha.posicion_del_recorte(None))

    def test_descripcion_de_la_portada(self):

        self.assertEqual(
            ficha.descripcion_de_la_portada(35, 4),
            "35 gatos y 4 perros buscan familia. Mirá sus fotos, conocé su historia y completá el formulario de pre-adopción para adoptar de forma responsable.",
        )
        self.assertTrue(ficha.descripcion_de_la_portada(1, 0).startswith("1 gato busca familia."))
        self.assertTrue(ficha.descripcion_de_la_portada(0, 2).startswith("2 perros buscan familia."))
        self.assertTrue(ficha.descripcion_de_la_portada(0, 0).startswith("Adopción responsable"))
