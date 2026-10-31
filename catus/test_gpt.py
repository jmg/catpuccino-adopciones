"""Reading the model's answer about an Instagram post.

Run with ENV=TEST (catus/config/config.test.json, sqlite):
    ENV=TEST python manage.py test catus.test_gpt
"""
from django.test import SimpleTestCase


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
