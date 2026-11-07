"""What the server fetches when a rescuer imports an Instagram post.

Run with ENV=TEST (catus/config/config.test.json, sqlite):
    ENV=TEST python manage.py test catus.test_instagram
"""
import io
import os
import shutil
import tempfile
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings
from PIL import Image


def jpeg_bytes():
    out = io.BytesIO()
    Image.new("RGB", (40, 30), "orange").save(out, "JPEG")
    return out.getvalue()


class FakeResponse:

    def __init__(self, status=200, body=b"", headers=None):
        self.status_code = status
        self.body = body
        self.headers = headers or {}
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(str(self.status_code))

    def iter_content(self, size):
        for i in range(0, len(self.body), size):
            yield self.body[i:i + size]

    def close(self):
        self.closed = True


class UrlChecksTest(SimpleTestCase):

    def test_photos_only_from_instagrams_cdn_over_https(self):
        from catus.utils import es_url_de_foto_de_instagram

        for url in (
            "https://scontent-gru2-1.cdninstagram.com/v/t51/123_n.jpg?stp=dst-jpg",
            "https://scontent.fepa1-1.fna.fbcdn.net/v/t39/456_n.jpg",
        ):
            self.assertTrue(es_url_de_foto_de_instagram(url), url)

        for url in (
            "file:///proc/self/environ",
            "file:///etc/secrets/catpuccino_adopciones.prod.json",
            "http://scontent.cdninstagram.com/foto.jpg",
            "https://cdninstagram.com.evil.example/foto.jpg",
            "https://evilfbcdn.net/foto.jpg",
            "https://scontent.cdninstagram.com@127.0.0.1/foto.jpg",
            "https://127.0.0.1/foto.jpg",
            "https://169.254.169.254/latest/meta-data/",
            "gopher://scontent.cdninstagram.com/",
            "",
            None,
        ):
            self.assertFalse(es_url_de_foto_de_instagram(url), url)

    def test_posts_only_from_instagram_over_https(self):
        from catus.utils import es_url_de_instagram

        self.assertTrue(es_url_de_instagram("https://www.instagram.com/p/C0d1g0/"))
        self.assertTrue(es_url_de_instagram("https://instagram.com/p/C0d1g0/"))
        for url in ("http://www.instagram.com/p/x/", "https://www.instagram.com.evil.example/p/x/",
                    "https://localhost:8888/", "file:///etc/passwd"):
            self.assertFalse(es_url_de_instagram(url), url)


class DescargarTest(SimpleTestCase):

    def test_a_redirect_out_of_the_allowed_hosts_is_not_followed(self):
        from catus.utils import DescargaRechazada, descargar, es_url_de_foto_de_instagram

        redirect = FakeResponse(302, headers={"Location": "http://127.0.0.1:8888/admin/"})
        with mock.patch("catus.utils.requests.get", return_value=redirect) as get:
            with self.assertRaises(DescargaRechazada):
                descargar("https://scontent.cdninstagram.com/foto.jpg", es_url_de_foto_de_instagram, 1000)

        self.assertEqual(get.call_count, 1)
        self.assertFalse(get.call_args[1]["allow_redirects"])

    def test_a_download_stops_at_the_size_cap(self):
        from catus.utils import DescargaRechazada, descargar, es_url_de_foto_de_instagram

        big = FakeResponse(200, body=b"x" * 5000)
        with mock.patch("catus.utils.requests.get", return_value=big):
            with self.assertRaises(DescargaRechazada):
                descargar("https://scontent.cdninstagram.com/foto.jpg", es_url_de_foto_de_instagram, 1000)

        self.assertTrue(big.closed)

    def test_the_post_page_is_not_fetched_from_another_host(self):
        from catus.services.gpt import GPTService

        with mock.patch("catus.utils.requests.get") as get:
            with self.assertRaises(ValueError):
                GPTService().pull_data_from_ig("http://169.254.169.254/latest/meta-data/")

        get.assert_not_called()


class ImportPhotosTest(TestCase):
    """The photo URLs (instagram_image) come from the browser: urlopen() read
    file:// too, and saved the server's own files as the animal's photos."""

    def setUp(self):
        from catus.models import Animal, CatusUser

        self.media = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.media, "gallery"))
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)

        self.owner = CatusUser.objects.create(username="refugio", email="refugio@example.com")
        self.animal = Animal.objects.create(nombre="Michi", cargado_por=self.owner, estado="D", tipo="G", aprobado=True)
        self.client.force_login(self.owner)

    def post(self, image_urls):
        return self.client.post("/animales/{}/".format(self.animal.id), {
            "tipo": "G", "estado": "D", "nombre": "Michi", "edad": "2 años", "sexo": "H", "zona": "CABA",
            "datos": "Muy mimosa",
            "animalimage_set-TOTAL_FORMS": "0", "animalimage_set-INITIAL_FORMS": "0",
            "animalimage_set-MIN_NUM_FORMS": "0", "animalimage_set-MAX_NUM_FORMS": "1000",
            "instagram_image": image_urls,
        })

    def test_a_local_file_is_never_read(self):
        secret = os.path.join(self.media, "secreto.json")
        with open(secret, "w") as f:
            f.write('{"DB_PASSWORD": "no-me-leas"}')

        with mock.patch("catus.utils.requests.get") as get:
            response = self.post(["file://" + secret, "http://127.0.0.1:8888/", "https://example.com/x.jpg"])

        # None of them is from Instagram's CDN, so none counts as the animal's photo:
        # the form comes back asking for one, and nothing was fetched.
        self.assertEqual(response.status_code, 200)
        get.assert_not_called()
        self.assertEqual(self.animal.animalimage_set.count(), 0)

    def test_a_photo_from_instagrams_cdn_is_imported(self):
        photo = FakeResponse(200, body=jpeg_bytes(), headers={"Content-Type": "image/jpeg"})
        with mock.patch("catus.utils.requests.get", return_value=photo):
            response = self.post(["https://scontent-gru2-1.cdninstagram.com/v/t51/123_n.jpg"])

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.animal.animalimage_set.count(), 1)

    def test_what_is_not_an_image_is_not_saved(self):
        page = FakeResponse(200, body=b"<html><script>alert(1)</script></html>")
        with mock.patch("catus.utils.requests.get", return_value=page):
            self.post(["https://scontent-gru2-1.cdninstagram.com/v/t51/123_n.jpg"])

        self.assertEqual(self.animal.animalimage_set.count(), 0)
