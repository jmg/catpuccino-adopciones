"""Reading the model's answer about an Instagram post.

Run with ENV=TEST (catus/config/config.test.json, sqlite):
    ENV=TEST python manage.py test catus.test_gpt
"""
from unittest import mock

from django.test import SimpleTestCase, TestCase


class ParseResponseTest(SimpleTestCase):
    """The answer is text the model wrote from a caption anyone can write: it is
    read as data, never run."""

    def parse(self, content):
        from catus.services.gpt import GPTService

        return GPTService().parse_response(content)

    def test_json(self):
        data = self.parse('{"nombre": "Michi", "tipo": "gato", "sexo": "hembra"}')

        self.assertEqual((data["Nombre"], data["Tipo"], data["Sexo"]), ("Michi", "G", "H"))

    def test_json_inside_a_code_fence(self):
        data = self.parse('```json\n{"nombre": "Toby", "tipo": "perro"}\n```')

        self.assertEqual((data["Nombre"], data["Tipo"]), ("Toby", "P"))

    def test_a_python_dict(self):
        data = self.parse("{'nombre': 'Michi', 'tipo': 'gato'}")

        self.assertEqual(data["Nombre"], "Michi")

    def test_code_is_not_run(self):
        import catus.services.gpt as gpt

        payload = "{'nombre': __import__('catus.services.gpt').services.gpt.__dict__.__setitem__('PWNED', 1)}"
        self.parse(payload)

        self.assertFalse(hasattr(gpt, "PWNED"))


class PullDataFromIgTest(TestCase):
    """"Obtener datos desde Instagram" asks a model that still exists: with the retired
    gpt-3.5-turbo the API answered InvalidRequestError and the button always failed."""

    def test_asks_a_current_model(self):
        from catus.services.gpt import GPTService

        respuesta = {"choices": [{"message": {"content": '{"nombre": "Pancho", "tipo": "gato"}'}}]}

        with mock.patch.object(GPTService, "_get_html_title_and_images", return_value=("Pancho, gato naranja", [])), \
                mock.patch("catus.services.gpt.openai.ChatCompletion.create", return_value=respuesta) as create:
            data = GPTService().pull_data_from_ig("https://www.instagram.com/p/DfayZB7FjpP/")

        self.assertEqual(create.call_args.kwargs["model"], "gpt-4o-mini")
        self.assertEqual((data["Nombre"], data["Tipo"]), ("Pancho", "G"))
