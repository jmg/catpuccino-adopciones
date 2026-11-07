"""Un rescatista no puede cargar dos veces el mismo animal.

Lo motivó un caso de producción (2026-11-02): una cuenta cargó al mismo perro dos veces
con 29 minutos de diferencia, con el mismo nombre, tipo, sexo, edad y texto, y las mismas
seis fotos, iguales byte a byte. El primero estaba esperando que el equipo lo aprobara y
la persona, como no lo veía publicado, lo volvió a cargar. El doble clic en "Guardar
Cambios" hacía lo mismo en un segundo. El equipo tenía que encontrar el repetido a mano,
y la revisión con IA se pagaba dos veces.

Todo va por EditView, como lo manda la pantalla. El primer animal también: lo que queda
en el disco es lo que dejó optimize(), no lo que se subió, y la comparación de fotos
tiene que encontrarlo igual.

Y frenar de más hace daño: un animal real que no se puede publicar. Por eso también están
los casos que se tienen que poder cargar.
"""
import hashlib
import os
import re
import shutil
import tempfile
import time
from datetime import timedelta
from unittest import mock

from django.contrib.sessions.middleware import SessionMiddleware
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from catus.models import Animal, AnimalImage
from catus.services.duplicados import DuplicadosService, normalizar
from catus.services.images import ImageService
from catus.tests.factories import make_animal, make_user, photo_bytes, uploaded_photo
from catus.views.animal import MAX_ANCHO_FOTO, EditView

TEMPLATE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates", "animal", "edit.html")

#cada color es una foto distinta; el mismo color, los mismos bytes
GRIS = (120, 120, 120)
MARRON = (150, 100, 60)
NEGRO = (20, 20, 20)
BLANCO = (235, 235, 235)
NARANJA = (220, 130, 40)
CREMA = (230, 210, 170)
AZULADO = (90, 110, 140)
ROJIZO = (170, 60, 40)

TEXTO = "<p>Perro muy bueno, juguetón y sociable. Se entrega castrado y vacunado.</p>"
OTRO_TEXTO = "<p>Le encanta pasear y dormir al sol. Ideal para una familia con patio.</p>"
TERCER_TEXTO = "<p>Tranquilo, se lleva bien con otros animales. Busca una casa sin apuro.</p>"

BYTES_OPTIMIZADOS = ImageService.bytes_optimizados


class AltaDuplicadaTestCase(TestCase):

    def setUp(self):
        #las altas guardan fotos de verdad: que caigan en un directorio descartable
        self.media = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.media, "gallery"))
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        self.addCleanup(shutil.rmtree, self.media, True)
        self.addCleanup(self.override.disable)

        self.factory = RequestFactory()
        self.rescatista = make_user(email="rescatista@catpuccino.test")

    def pedido(self, url, datos, usuario):

        request = self.factory.post(url, datos)
        request.user = usuario or self.rescatista

        SessionMiddleware(lambda request: None).process_request(request)
        request.session.save()

        return request

    def alta(self, nombre="Rocco", tipo="P", sexo="M", edad="2 años", texto=TEXTO,
             colores=(GRIS, MARRON), usuario=None, instagram=None):
        """El POST de "Nuevo Animal" tal como lo arma la pantalla, con una foto por color."""

        datos = {
            "tipo": tipo, "estado": "D", "nombre": nombre, "edad": edad, "sexo": sexo,
            "zona": "CABA", "datos": texto,
            "animalimage_set-TOTAL_FORMS": str(len(colores)),
            "animalimage_set-INITIAL_FORMS": "0",
            "animalimage_set-MIN_NUM_FORMS": "0",
            "animalimage_set-MAX_NUM_FORMS": "1000",
        }

        #un archivo nuevo en cada pedido: RequestFactory lee el que le pasan
        for indice, color in enumerate(colores):
            datos["animalimage_set-{}-image".format(indice)] = uploaded_photo(name="foto-{}.jpg".format(indice), color=color)

        if instagram:
            datos["instagram_image"] = instagram

        request = self.pedido("/animales/", datos, usuario)

        #se mockea sólo lo que sale a la red: el mail y la bajada de fotos de Instagram
        with mock.patch("catus.views.animal.MailService") as self.mail, \
                mock.patch("catus.views.animal.bajar_foto_de_instagram",
                           return_value=photo_bytes(color=BLANCO).getvalue()) as self.bajar:
            return EditView.as_view(template_name="animal/edit.html")(request)

    def animales(self, usuario=None):

        return Animal.objects.filter(cargado_por=usuario or self.rescatista)

    def primero(self, **kwargs):
        """El animal que ya estaba cargado: se carga por la vista, como el del incidente."""

        response = self.alta(**kwargs)
        self.assertEqual(response.status_code, 302, "no se pudo cargar el primero: el POST del test quedó viejo")

        return self.animales(kwargs.get("usuario")).latest("id")

    def con_foto_sin_optimizar(self, color, nombre="Rocco"):
        """Un animal con una foto guardada tal cual se subió, como las del admin o las viejas."""

        animal = make_animal(nombre=nombre, tipo="P", cargado_por=self.rescatista, aprobado=False)
        imagen = AnimalImage(animal=animal)
        imagen.image.save("foto.jpg", uploaded_photo(color=color), save=True)

        return animal

    def errores(self, response):

        self.assertEqual(response.status_code, 200, "no volvió al formulario")
        self.assertFalse(response.context_data["success"])

        return " ".join(str(error) for error in response.context_data["errors"])

    def archivos_en_la_galeria(self):

        return sorted(os.listdir(os.path.join(self.media, "gallery")))


class FotosRepetidasTest(AltaDuplicadaTestCase):

    def test_las_mismas_fotos_no_cargan_otro_animal(self):
        """El incidente, con el texto retocado: sólo las fotos lo delatan.

        Lo guardado es lo que dejó optimize() (reencodado a JPEG 70), así que comparar el
        archivo subido contra el del disco no encontraba nunca nada.
        """

        anterior = self.primero()

        response = self.alta(texto=OTRO_TEXTO)

        self.assertEqual(self.animales().count(), 1, "se cargó dos veces el mismo animal")
        errores = self.errores(response)
        self.assertIn("Ya cargaste a Rocco", errores)
        self.assertIn('<a href="/animales/{0}/">/animales/{0}/</a>'.format(anterior.id), errores)

    def test_no_guarda_nada_ni_las_fotos(self):

        self.primero()
        archivos = self.archivos_en_la_galeria()
        fotos = AnimalImage.objects.count()

        self.alta(texto=OTRO_TEXTO)

        self.assertEqual(AnimalImage.objects.count(), fotos)
        self.assertEqual(self.archivos_en_la_galeria(), archivos, "quedaron fotos sueltas en el disco")
        self.assertFalse(self.mail.called, "se avisó del alta de un animal que no se guardó")

    def test_el_mismo_nombre_con_una_foto_repetida_es_el_mismo(self):
        """Con el mismo nombre alcanza una foto en común, aunque traiga otras."""

        self.primero()

        response = self.alta(texto=OTRO_TEXTO, colores=(GRIS, NEGRO))

        self.assertEqual(self.animales().count(), 1)
        errores = self.errores(response)
        self.assertIn("Ya cargaste a Rocco", errores)
        self.assertIn("cambiale el nombre", errores, "lo que los confunde es el nombre")

    def test_con_otro_nombre_y_todas_las_fotos_iguales_tambien_es_el_mismo(self):
        """El mismo animal cargado de nuevo con el nombre corregido."""

        self.primero()

        response = self.alta(nombre="Rocco (cachorro)", texto=OTRO_TEXTO)

        self.assertEqual(self.animales().count(), 1)
        self.assertIn("Ya cargaste a Rocco", self.errores(response))

    def test_las_mismas_seis_fotos_con_otro_nombre_no_cargan_otro_animal(self):
        """Las seis fotos del incidente, con otro nombre y otro texto."""

        seis = (GRIS, MARRON, NEGRO, NARANJA, CREMA, AZULADO)
        self.primero(colores=seis)

        response = self.alta(nombre="Toto", texto=OTRO_TEXTO, colores=seis)

        self.assertEqual(self.animales().count(), 1, "se cargó dos veces el mismo animal")
        errores = self.errores(response)
        self.assertIn("Ya cargaste a Rocco", errores)
        self.assertIn("sumale al menos una foto que no esté en esa publicación", errores)

    def test_un_hermano_con_la_foto_de_la_camada_se_carga(self):
        """Una sola foto en común no alcanza si el nombre es otro.

        Los hermanos de una camada se publican cada uno por su lado y es normal que
        compartan la foto de todos juntos: con "alguna foto repetida" a secas, el segundo
        hermano no se podía cargar.
        """

        self.primero(nombre="Mía", tipo="G", sexo="H", colores=(GRIS, MARRON))

        response = self.alta(nombre="Simba", tipo="G", sexo="M", texto=OTRO_TEXTO, colores=(GRIS, NEGRO))

        self.assertEqual(response.status_code, 302, "no dejó cargar al hermano")
        self.assertEqual(self.animales().count(), 2)

    def test_un_hermano_con_solo_la_foto_de_la_camada_se_carga(self):
        """Su única foto es la de todos juntos, que ya está en el hermano.

        Con "todas las fotos del alta ya están en ese animal" se frenaba: una sola foto
        siempre es "todas".
        """

        self.primero(nombre="Mía", tipo="G", sexo="H", colores=(GRIS, MARRON))

        response = self.alta(nombre="Simba", tipo="G", sexo="M", texto=OTRO_TEXTO, colores=(GRIS,))

        self.assertEqual(response.status_code, 302, "no dejó cargar al hermano")
        self.assertEqual(self.animales().count(), 2)

    def test_un_flyer_como_unica_foto_no_frena_al_siguiente(self):
        """Hay cuentas que suben el mismo flyer como única foto de cada animal."""

        self.primero(nombre="Luna", tipo="G", sexo="H", colores=(NARANJA,))

        response = self.alta(nombre="Toto", tipo="G", sexo="M", texto=OTRO_TEXTO, colores=(NARANJA,))

        self.assertEqual(response.status_code, 302, "el flyer frenó a otro animal")
        self.assertEqual(self.animales().count(), 2)

    def test_la_publicacion_de_uno_solo_puede_reusar_una_foto_de_la_camada(self):
        """La camada se publicó junta y después uno sale por su lado con su foto de ahí."""

        self.primero(nombre="Camada Michis", tipo="G", sexo="A", colores=(GRIS, MARRON, NEGRO))

        response = self.alta(nombre="Michi naranja", tipo="G", sexo="M", texto=OTRO_TEXTO, colores=(MARRON,))

        self.assertEqual(response.status_code, 302, "no dejó publicar a uno de la camada con su foto")
        self.assertEqual(self.animales().count(), 2)

    def test_la_misma_foto_subida_dos_veces_cuenta_como_una(self):
        """Dos veces el flyer sigue siendo una sola foto, no "todas las fotos"."""

        self.primero(nombre="Luna", tipo="G", sexo="H", colores=(NARANJA,))

        response = self.alta(nombre="Toto", tipo="G", sexo="M", texto=OTRO_TEXTO, colores=(NARANJA, NARANJA))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.animales().count(), 2)

    def test_todas_las_fotos_tienen_que_estar_en_el_mismo_animal(self):
        """Repartidas entre dos animales distintos son fotos reusadas, no el mismo."""

        self.primero(nombre="Mía", tipo="G", sexo="H", colores=(GRIS, MARRON))
        self.primero(nombre="Luna", tipo="G", sexo="H", texto=OTRO_TEXTO, colores=(NEGRO, NARANJA))

        response = self.alta(nombre="Simba", tipo="G", sexo="M", texto=TERCER_TEXTO, colores=(GRIS, NEGRO))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.animales().count(), 3)

    def test_una_foto_guardada_sin_optimizar_tambien_cuenta(self):
        """Las que no pasaron por optimize() (el admin, cargas viejas) quedan tal cual."""

        anterior = self.con_foto_sin_optimizar(GRIS)

        response = self.alta(texto=OTRO_TEXTO, colores=(GRIS,))

        self.assertEqual(self.animales().count(), 1)
        self.assertIn("/animales/{}/".format(anterior.id), self.errores(response))

    def test_lo_que_compara_es_lo_que_guarda_optimize(self):
        """La comparación rehace la cuenta de optimize(): si se separan, deja de encontrar."""

        crudo = photo_bytes(size=(2400, 1800), color=MARRON).getvalue()

        imagen = AnimalImage(animal=make_animal(cargado_por=self.rescatista))
        imagen.image.save("grande.jpg", SimpleUploadedFile("grande.jpg", crudo), save=True)
        ImageService().optimize(imagen.image, max_width=MAX_ANCHO_FOTO)

        with open(imagen.image.path, "rb") as guardada:
            en_el_disco = hashlib.sha256(guardada.read()).hexdigest()

        rehecha = ImageService().bytes_optimizados(SimpleUploadedFile("grande.jpg", crudo), MAX_ANCHO_FOTO)

        self.assertEqual(hashlib.sha256(rehecha).hexdigest(), en_el_disco)


class CostoDeLasFotosTest(AltaDuplicadaTestCase):
    """Comparar fotos corre en el POST del alta: lee del disco y reencoda, así que tiene topes."""

    def test_si_la_foto_ya_coincidio_tal_cual_no_la_reencoda(self):
        """Rehacer optimize() es lo caro. Si el archivo ya está guardado tal cual (una carga
        vieja, el admin, una foto bajada del sitio y vuelta a subir), no hace falta."""

        self.con_foto_sin_optimizar(GRIS)

        with mock.patch.object(ImageService, "bytes_optimizados", autospec=True,
                               side_effect=BYTES_OPTIMIZADOS) as reencodar:
            response = self.alta(texto=OTRO_TEXTO, colores=(GRIS, NEGRO))

        self.assertEqual(self.animales().count(), 1)
        self.assertIn("Ya cargaste a Rocco", self.errores(response))
        self.assertEqual(reencodar.call_count, 1, "reencodó la foto que ya había coincidido tal cual")

    def test_con_una_sola_foto_y_otro_nombre_no_lee_ninguna_foto_guardada(self):
        """Ahí no hay regla que pueda dar: no vale la pena tocar el disco."""

        self.primero()

        with mock.patch.object(DuplicadosService, "sha256_del_archivo") as leer:
            response = self.alta(nombre="Toto", texto=OTRO_TEXTO, colores=(GRIS,))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(leer.called, "leyó las fotos guardadas para nada")

    def test_entre_todas_las_fotos_guardadas_hay_un_tope_de_bytes(self):
        """Con sólo los topes de cantidad y de tamaño de cada una, 120 fotos de 20 MB eran
        2,4 GB leídos en un POST. Se leen primero las de los animales más nuevos."""

        viejo = self.con_foto_sin_optimizar(GRIS, nombre="Viejo")
        medio = self.con_foto_sin_optimizar(MARRON, nombre="Medio")
        nuevo = self.con_foto_sin_optimizar(NEGRO, nombre="Nuevo")

        def tamano(animal):
            return animal.animalimage_set.get().image.size

        tope = tamano(nuevo) + tamano(medio)

        with mock.patch.object(DuplicadosService, "MAX_BYTES_FOTOS_GUARDADAS", tope), \
                mock.patch.object(DuplicadosService, "sha256_del_archivo",
                                  autospec=True, side_effect=DuplicadosService.sha256_del_archivo) as leer:
            huellas = DuplicadosService().huellas_guardadas([nuevo, medio, viejo])

        self.assertEqual(set(huellas), {nuevo.id, medio.id})
        self.assertEqual(leer.call_count, 2, "leyó más de lo que entraba en el tope")


class LoSubidoSeGuardaEnteroTest(AltaDuplicadaTestCase):
    """Comparar lee las fotos subidas hasta el final, y después la vista las guarda."""

    def test_despues_de_comparar_cada_foto_queda_al_principio(self):
        """Hoy el storage de Django rebobina antes de guardar, así que olvidarse no rompe
        nada a la vista. Pero lo que quede en otra posición se lee cortado o vacío por
        cualquiera que lea el archivo sin rebobinar."""

        self.primero(colores=(GRIS, MARRON))
        self.con_foto_sin_optimizar(BLANCO, nombre="Luna")

        #GRIS se reencoda para compararla; BLANCO coincide tal cual y no
        fotos = [uploaded_photo(name="a.jpg", color=GRIS), uploaded_photo(name="b.jpg", color=BLANCO)]
        datos = {"nombre": "Toto", "tipo": "P", "sexo": "M", "edad": "2 años", "datos": OTRO_TEXTO}

        duplicado = DuplicadosService().buscar(self.rescatista, datos, fotos_subidas=fotos, max_width=MAX_ANCHO_FOTO)

        self.assertIsNone(duplicado, "las fotos están en dos animales distintos: no es el mismo")
        for foto in fotos:
            self.assertEqual(foto.tell(), 0, "la foto quedó leída: se guardaría cortada")

    def test_lo_guardado_es_optimize_de_la_foto_entera(self):

        self.primero(colores=(GRIS, MARRON))

        response = self.alta(nombre="Toto", texto=OTRO_TEXTO, colores=(GRIS, NEGRO))
        self.assertEqual(response.status_code, 302)

        esperado = {
            hashlib.sha256(ImageService().bytes_optimizados(uploaded_photo(color=color), MAX_ANCHO_FOTO)).hexdigest()
            for color in (GRIS, NEGRO)
        }

        guardado = set()
        for imagen in self.animales().latest("id").animalimage_set.all():
            with open(imagen.image.path, "rb") as archivo:
                guardado.add(hashlib.sha256(archivo.read()).hexdigest())

        self.assertEqual(guardado, esperado)


class MismosDatosTest(AltaDuplicadaTestCase):

    def test_los_mismos_datos_con_otras_fotos_no_cargan_otro_animal(self):
        """Mismo nombre, tipo, sexo, edad y texto, aunque el editor lo devuelva distinto."""

        self.primero()

        response = self.alta(
            nombre="  rocco ", edad="2  AÑOS",
            texto="<div>Perro muy  bueno, juguetón&nbsp;y sociable.</div><div>Se entrega castrado y vacunado.</div>",
            colores=(NEGRO,),
        )

        self.assertEqual(self.animales().count(), 1, "se cargó dos veces el mismo animal")
        errores = self.errores(response)
        self.assertIn("Ya cargaste a Rocco", errores)
        self.assertIn("cambiale el nombre", errores)

    def test_el_mismo_nombre_con_otras_fotos_y_otro_texto_se_carga(self):
        """Luna, Mía y Simba se repiten todo el tiempo: el nombre solo no dice nada."""

        self.primero(nombre="Luna", tipo="G", sexo="H")

        response = self.alta(nombre="Luna", tipo="G", sexo="H", texto=OTRO_TEXTO, colores=(NEGRO,))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.animales().count(), 2)

    def test_con_otra_edad_es_otro_animal(self):

        self.primero()

        response = self.alta(edad="3 meses", colores=(NEGRO,))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.animales().count(), 2)

    def test_tambien_frena_el_alta_que_trae_solo_fotos_de_instagram(self):
        """Esas fotos se bajan después de guardar, así que acá sólo quedan los datos."""

        self.primero()

        response = self.alta(colores=(), instagram="https://scontent.cdninstagram.com/v/foto.jpg")

        self.assertEqual(self.animales().count(), 1)
        self.assertIn("Ya cargaste a Rocco", self.errores(response))
        self.assertFalse(self.bajar.called, "se bajaron fotos para un animal que no se guardó")


class TextoEnormeTest(AltaDuplicadaTestCase):
    """El texto lo manda cualquiera que se registre, no tiene tope de largo, y se compara
    en cada alta contra el de hasta 200 animales.

    Sacarle el HTML con r"<[^>]*>" era cuadrático con '<' sin cerrar: '<' * 100.000 tardaba
    3,5 s y 200.000, 14 s, con el GIL tomado. En producción eso traba un worker entero de
    gunicorn con sus 4 threads, y con dos POST se cae el sitio hasta el timeout de 180 s.
    """

    def test_un_alta_con_etiquetas_sin_cerrar_de_una_cuenta_nueva_responde_rapido(self):
        """La cuenta no tiene ningún animal: igual se normaliza lo que manda."""

        nueva = make_user(email="nueva@catpuccino.test")

        inicio = time.perf_counter()
        response = self.alta(texto="<" * 200_000, usuario=nueva)
        demora = time.perf_counter() - inicio

        self.assertEqual(response.status_code, 302)
        self.assertLess(demora, 2, "el alta tardó {:.1f} s".format(demora))

    def test_un_texto_guardado_enorme_no_traba_el_alta_siguiente(self):
        """Editar no pasa por la búsqueda, así que el texto guardado puede ser cualquier cosa."""

        make_animal(nombre="Rocco", tipo="P", sexo="M", cargado_por=self.rescatista, datos="<" * 1_000_000)

        inicio = time.perf_counter()
        response = self.alta(colores=(NEGRO,))
        demora = time.perf_counter() - inicio

        self.assertEqual(response.status_code, 302)
        self.assertLess(demora, 2, "el alta tardó {:.1f} s".format(demora))

    def test_del_texto_guardado_trae_de_la_base_solo_el_principio(self):
        """Traerlo entero de hasta 200 animales podían ser cientos de MB por alta.

        Y el texto se trae sólo del que ya coincide en nombre y edad: con otro nombre, la
        columna ni aparece.
        """

        make_animal(nombre="Toto", edad="2 años", tipo="P", sexo="M", cargado_por=self.rescatista, datos="x" * 50_000)
        make_animal(nombre="Rocco", edad="2 años", tipo="P", sexo="M", cargado_por=self.rescatista, datos="y" * 50_000)

        datos = {"nombre": "Toto", "tipo": "P", "sexo": "M", "edad": "2 años", "datos": TEXTO}

        with CaptureQueriesContext(connection) as consultas:
            DuplicadosService().buscar(self.rescatista, datos)

        columna = "{}.{}".format(connection.ops.quote_name("catus_animal"), connection.ops.quote_name("datos"))
        recortada = re.compile(r"SUBSTR(?:ING)?\(\s*" + re.escape(columna), re.IGNORECASE)

        self.assertTrue(any(recortada.search(consulta["sql"]) for consulta in consultas), "no recortó el texto en la base")
        for consulta in consultas:
            self.assertNotIn(columna, recortada.sub("", consulta["sql"]), "trajo de la base el texto entero")

        with CaptureQueriesContext(connection) as consultas:
            DuplicadosService().buscar(self.rescatista, dict(datos, nombre="Simba"))

        for consulta in consultas:
            self.assertNotIn(columna, consulta["sql"], "trajo el texto de animales que se llaman distinto")

    def test_del_texto_se_compara_el_principio(self):
        """Recortado igual de los dos lados: si recién se separan después, es el mismo."""

        comun = "<p>" + "Muy bueno y juguetón. " * 1000 + "</p>"
        self.assertGreater(len(comun), DuplicadosService.MAX_CARACTERES_TEXTO)

        self.primero(texto=comun + "<p>Final uno</p>")

        response = self.alta(texto=comun + "<p>Final dos</p>", colores=(NEGRO,))

        self.assertEqual(self.animales().count(), 1)
        self.assertIn("Ya cargaste a Rocco", self.errores(response))


class LoQueNoEsDuplicadoTest(AltaDuplicadaTestCase):

    def test_si_el_anterior_expiro_se_puede_volver_a_cargar(self):

        anterior = self.primero()
        Animal.objects.filter(id=anterior.id).update(estado="E")

        self.assertEqual(self.alta().status_code, 302)
        self.assertEqual(self.animales().count(), 2)

    def test_si_el_anterior_se_adopto_se_puede_volver_a_cargar(self):
        """Volvió a quedar en adopción: es otra publicación."""

        anterior = self.primero()
        Animal.objects.filter(id=anterior.id).update(estado="A", fecha_adopcion=timezone.now())

        self.assertEqual(self.alta().status_code, 302)
        self.assertEqual(self.animales().count(), 2)

    def test_lo_mismo_desde_otra_cuenta_se_carga(self):
        """Dos rescatistas pueden publicar al mismo animal: eso lo resuelve el equipo."""

        self.primero()
        otra = make_user(email="otra@catpuccino.test")

        response = self.alta(usuario=otra)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.animales(otra).count(), 1)

    def test_un_animal_cargado_hace_mas_de_90_dias_no_cuenta(self):

        anterior = self.primero()
        Animal.objects.filter(id=anterior.id).update(created_at=timezone.now() - timedelta(days=91))

        self.assertEqual(self.alta().status_code, 302)
        self.assertEqual(self.animales().count(), 2)


class EditarNoSeVeAfectadoTest(AltaDuplicadaTestCase):
    """La búsqueda es del alta: editar un animal no lo duplica."""

    def editar(self, animal, **cambios):

        imagenes = list(animal.get_images())

        datos = {
            "tipo": animal.tipo, "estado": animal.estado, "nombre": animal.nombre,
            "edad": animal.edad or "", "sexo": animal.sexo, "zona": animal.zona or "",
            "datos": animal.datos or "",
            "animalimage_set-TOTAL_FORMS": str(len(imagenes)),
            "animalimage_set-INITIAL_FORMS": str(len(imagenes)),
            "animalimage_set-MIN_NUM_FORMS": "0",
            "animalimage_set-MAX_NUM_FORMS": "1000",
        }
        for indice, imagen in enumerate(imagenes):
            datos["animalimage_set-{}-id".format(indice)] = str(imagen.id)
            datos["animalimage_set-{}-animal".format(indice)] = str(animal.id)

        datos.update(cambios)

        request = self.pedido("/animales/{}/".format(animal.id), datos, None)

        with mock.patch("catus.views.animal.MailService"):
            return EditView.as_view(template_name="animal/edit.html")(request, animal_id=str(animal.id))

    def test_editar_un_animal_ya_cargado_anda(self):
        """Lo guardado coincide en todo con lo que se manda: es el mismo animal."""

        animal = self.primero()

        response = self.editar(animal, zona="Palermo")

        self.assertEqual(response.status_code, 302)
        animal.refresh_from_db()
        self.assertEqual(animal.zona, "Palermo")

    def test_editar_uno_para_que_quede_igual_a_otro_tambien_anda(self):

        rocco = self.primero()
        otro = self.primero(nombre="Toto", texto=OTRO_TEXTO, colores=(NEGRO,))

        response = self.editar(otro, nombre=rocco.nombre, datos=rocco.datos)

        self.assertEqual(response.status_code, 302)
        otro.refresh_from_db()
        self.assertEqual(otro.nombre, "Rocco")


class DobleEnvioTest(AltaDuplicadaTestCase):

    def test_dos_envios_iguales_seguidos_dejan_uno_solo(self):
        """Dos POST iguales, el segundo cuando el primero ya se guardó: lo frena el server.

        Si llegan pegados pasan los dos, porque busca y después guarda sin lock. Contra el
        doble clic, que los manda casi juntos, protege la guarda del botón en
        animal/edit.html (jstests/guardar.spec.js).
        """

        primera = self.alta()
        segunda = self.alta()

        self.assertEqual(primera.status_code, 302)
        self.assertEqual(self.animales().count(), 1, "el segundo envío cargó otro animal")
        self.assertEqual(AnimalImage.objects.count(), 2, "quedaron fotos del segundo envío")
        self.assertIn("Ya cargaste a Rocco", self.errores(segunda))


class AvisoTest(AltaDuplicadaTestCase):
    """El aviso dice lo que la persona no sabía: que ya está cargado, y en qué anda."""

    def test_si_espera_aprobacion_lo_dice(self):

        self.primero()

        errores = self.errores(self.alta())

        self.assertIn("esperando que el equipo lo revise y lo apruebe", errores)
        self.assertIn("no hace falta cargarlo de nuevo", errores)

    def test_si_ya_esta_publicado_lo_dice(self):

        anterior = self.primero()
        Animal.objects.filter(id=anterior.id).update(aprobado=True)

        errores = self.errores(self.alta())

        self.assertIn("Ya está publicado", errores)
        self.assertNotIn("esperando", errores)

    def test_un_reservado_tambien_cuenta(self):

        anterior = self.primero()
        Animal.objects.filter(id=anterior.id).update(aprobado=True, estado="R")

        errores = self.errores(self.alta())

        self.assertEqual(self.animales().count(), 1)
        self.assertIn("reservado", errores)

    def test_dice_cuando_lo_cargo(self):

        anterior = self.primero()

        errores = self.errores(self.alta())

        self.assertIn(timezone.localtime(anterior.created_at).strftime("%d/%m/%Y"), errores)

    def test_el_nombre_con_html_sale_escapado(self):
        """El nombre lo escribe cualquiera que se registre, y el aviso lleva HTML propio
        (el link): se arma con format_html, así que el nombre no puede salir crudo."""

        self.primero(nombre="<script>alert(1)</script>")

        response = self.alta(nombre="<script>alert(1)</script>", texto=OTRO_TEXTO)
        html = response.render().content.decode()

        self.assertNotIn("<script>alert(1)</script>", html, "el nombre salió sin escapar")
        self.assertIn("Ya cargaste a &lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertRegex(html, r'<a href="/animales/\d+/">/animales/\d+/</a>', "el link no salió como link")


class GuardaDelBotonTest(SimpleTestCase):
    """Del lado del navegador: "Guardar Cambios" se apaga en cuanto sale el formulario.

    Lo que hace se prueba en un navegador de verdad (jstests/guardar.spec.js). Acá se
    cuida que siga en el template y donde lo encuentra ese test: en el único <script>
    inline, sin sintaxis de Django adentro.
    """

    def script(self):

        with open(TEMPLATE, encoding="utf-8") as archivo:
            bloques = re.findall(r"<script>([\s\S]*?)</script>", archivo.read())

        self.assertEqual(len(bloques), 1, "jstests espera un solo <script> inline en animal/edit.html")

        return bloques[0]

    def test_apaga_los_dos_botones_de_guardar(self):

        script = self.script()

        self.assertIn("#send-form-button, #send-form-button-bottom", script)
        self.assertIn("boton.disabled = true", script)

    def test_los_vuelve_a_prender_al_volver_atras(self):

        script = self.script()

        self.assertIn("addEventListener('pageshow'", script)
        self.assertIn("boton.disabled = false", script)

    def test_los_vuelve_a_prender_si_la_navegacion_se_corta(self):
        """Detener o Esc durante la subida no cambian de página ni mandan pageshow."""

        script = self.script()

        self.assertIn("REINTENTAR_DESPUES_DE_MS = 90000", script)
        self.assertIn("setTimeout(prenderBotones, REINTENTAR_DESPUES_DE_MS)", script)

    def test_no_los_apaga_si_la_validacion_freno_el_envio(self):

        self.assertIn("event.defaultPrevented", self.script())


class NormalizarTest(SimpleTestCase):

    def test_saca_el_html_y_las_entidades(self):

        self.assertEqual(normalizar("<p>Muy&nbsp;bueno</p><p>y &aacute;gil</p>"), "muy bueno y ágil")

    def test_saca_las_etiquetas_con_atributos(self):

        self.assertEqual(normalizar('<p style="text-align: center;"><strong>Rocco</strong></p>'), "rocco")

    def test_colapsa_los_espacios_y_no_distingue_mayusculas(self):

        self.assertEqual(normalizar("  Rocco \n  EL   Grande "), "rocco el grande")

    def test_nada_es_vacio(self):

        self.assertEqual(normalizar(None), "")
        self.assertEqual(normalizar(""), "")

    def test_con_etiquetas_sin_cerrar_no_se_traba(self):
        """r"<[^>]*>" era cuadrático: cada '<' sin cerrar recorría el resto del texto."""

        for texto in ("<" * 200_000, "<a" * 100_000):
            inicio = time.perf_counter()
            normalizar(texto)
            demora = time.perf_counter() - inicio

            self.assertLess(demora, 0.5, "normalizar volvió a ser cuadrático: {:.1f} s".format(demora))


class ConjuntoDeFotosTest(AltaDuplicadaTestCase):
    """La regla "fotos" pide el mismo conjunto, el mismo tipo y el mismo sexo.

    Con "todas las fotos del alta ya están en ese animal" se frenaba a un gatito que salía por
    su lado con dos fotos de la publicación de su camada, y el aviso le pedía "subí sus
    propias fotos" cuando eran las suyas. También a una gata y una perra que comparten el
    flyer, y a una pareja de macho y hembra con las mismas fotos de los dos.
    """

    def test_un_gatito_puede_reusar_dos_fotos_de_la_publicacion_de_su_camada(self):

        self.primero(nombre="Camada Michis", tipo="G", sexo="A", colores=(GRIS, MARRON, NEGRO, NARANJA))

        response = self.alta(nombre="Michi naranja", tipo="G", sexo="A", texto=OTRO_TEXTO, colores=(MARRON, NEGRO))

        self.assertEqual(response.status_code, 302, "no dejó publicar a uno de la camada con sus fotos de ahí")
        self.assertEqual(self.animales().count(), 2)

    def test_una_pareja_de_macho_y_hembra_con_las_mismas_fotos_se_carga(self):

        self.primero(nombre="Pancho", tipo="G", sexo="M", colores=(GRIS, MARRON))

        response = self.alta(nombre="Lola", tipo="G", sexo="H", texto=OTRO_TEXTO, colores=(GRIS, MARRON))

        self.assertEqual(response.status_code, 302, "frenó a la otra mitad de la pareja")
        self.assertEqual(self.animales().count(), 2)

    def test_luna_gata_y_luna_perra_con_el_mismo_flyer_se_cargan(self):

        self.primero(nombre="Luna", tipo="G", sexo="H", colores=(NARANJA,))

        response = self.alta(nombre="Luna", tipo="P", sexo="H", texto=OTRO_TEXTO, colores=(NARANJA,))

        self.assertEqual(response.status_code, 302, "una gata y una perra no son el mismo animal")
        self.assertEqual(self.animales().count(), 2)

    def test_exactamente_las_mismas_fotos_del_mismo_sexo_frena_y_dice_como_seguir(self):
        """Es el compromiso que queda: dos del mismo sexo con exactamente las mismas fotos se
        frenan, y el aviso dice cómo destrabarlo."""

        self.primero(nombre="Pancho", tipo="G", sexo="M", colores=(GRIS, MARRON))

        response = self.alta(nombre="Tito", tipo="G", sexo="M", texto=OTRO_TEXTO, colores=(GRIS, MARRON))

        self.assertEqual(self.animales().count(), 1)
        self.assertIn("sumale al menos una foto que no esté en esa publicación", self.errores(response))

    def test_sumando_una_foto_que_no_esta_se_carga(self):

        self.primero(nombre="Pancho", tipo="G", sexo="M", colores=(GRIS, MARRON))

        response = self.alta(nombre="Tito", tipo="G", sexo="M", texto=OTRO_TEXTO, colores=(GRIS, MARRON, NEGRO))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.animales().count(), 2)

    def test_el_anterior_con_una_foto_mas_no_es_el_mismo_conjunto(self):

        self.primero(nombre="Pancho", tipo="G", sexo="M", colores=(GRIS, MARRON, NEGRO))

        response = self.alta(nombre="Tito", tipo="G", sexo="M", texto=OTRO_TEXTO, colores=(GRIS, MARRON))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.animales().count(), 2)


class CuandoNoAplicaLaReglaDeLasFotosTest(AltaDuplicadaTestCase):
    """Para "fotos" hay que ver todas las fotos del alta: si no se puede, queda la del nombre."""

    def setUp(self):
        super().setUp()
        self.primero(nombre="Rocco", colores=(GRIS, MARRON))

    def test_con_fotos_de_instagram_no_aplica(self):

        response = self.alta(nombre="Toto", texto=OTRO_TEXTO, colores=(GRIS, MARRON), instagram="https://scontent.cdninstagram.com/v/foto.jpg")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.animales().count(), 2)

    def test_con_una_foto_que_no_se_pudo_leer_no_aplica(self):

        original = DuplicadosService.huellas_crudas

        def con_una_ilegible(servicio, archivos):
            huellas, _ = original(servicio, archivos)
            return huellas, 1

        with mock.patch.object(DuplicadosService, "huellas_crudas", con_una_ilegible):
            response = self.alta(nombre="Toto", texto=OTRO_TEXTO, colores=(GRIS, MARRON))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.animales().count(), 2)

    def test_con_mas_fotos_que_el_tope_no_aplica(self):

        with mock.patch.object(DuplicadosService, "MAX_FOTOS_SUBIDAS", 1):
            response = self.alta(nombre="Toto", texto=OTRO_TEXTO, colores=(GRIS, MARRON))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.animales().count(), 2)

    def test_con_el_mismo_nombre_igual_frena_aunque_traiga_fotos_de_instagram(self):

        response = self.alta(nombre="Rocco", texto=OTRO_TEXTO, colores=(GRIS, NEGRO), instagram="https://scontent.cdninstagram.com/v/foto.jpg")

        self.assertEqual(self.animales().count(), 1)
        self.assertIn("cambiale el nombre", self.errores(response))


class DatosSinTextoTest(AltaDuplicadaTestCase):

    def test_dos_cachorros_sin_edad_ni_texto_con_otras_fotos_se_cargan(self):
        """Nombre genérico, edad y texto vacíos (son opcionales): son dos cachorros."""

        self.primero(nombre="Cachorro", edad="", texto="", colores=(GRIS,))

        response = self.alta(nombre="Cachorro", edad="", texto="", colores=(NEGRO,))

        self.assertEqual(response.status_code, 302, "frenó a otro cachorro sin texto")
        self.assertEqual(self.animales().count(), 2)


class TextoAdversarialTest(AltaDuplicadaTestCase):

    def test_una_referencia_numerica_enorme_no_da_un_500(self):
        """html.unescape le hace int() y Python 3.12 corta en 4300 dígitos con ValueError."""

        self.assertEqual(normalizar("<p>&#" + "9" * 4301 + ";</p>").strip(), "")

        response = self.alta(texto="<p>&#" + "9" * 4301 + ";</p>")

        self.assertEqual(response.status_code, 302)

    def test_un_texto_guardado_con_una_referencia_enorme_no_rompe_las_altas_siguientes(self):

        anterior = self.primero()
        Animal.objects.filter(id=anterior.id).update(datos="<p>&#" + "1" * 5000 + ";</p>")

        response = self.alta(nombre="Rocco", texto="<p>&#" + "1" * 5000 + ";</p>", colores=(NEGRO, NARANJA))

        self.assertIn(response.status_code, (200, 302))

    def test_normalizar_no_agranda_el_texto(self):
        """NFKC agrandaba U+FDFA 18 veces; NFC no."""

        self.assertLessEqual(len(normalizar("\ufdfa" * 20000)), 20000)

    def test_muchos_animales_con_texto_que_crece_no_traban_el_alta(self):

        Animal.objects.bulk_create([
            Animal(nombre="Rocco", tipo="P", sexo="M", edad="2 años", estado="D", datos="\ufdfa" * 20000, cargado_por=self.rescatista)
            for _ in range(200)
        ])

        empieza = time.monotonic()
        self.alta(texto="\ufdfa" * 20000, colores=(NEGRO,))
        tardo = time.monotonic() - empieza

        self.assertLess(tardo, 3.0, "el alta tardó {:.1f} s".format(tardo))
