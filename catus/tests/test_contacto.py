"""Los botones de WhatsApp, llamada y mail de la página de un formulario.

El celular y el mail los escribe cualquiera en el formulario público: nada de eso puede
llegar tal cual a un href, y un link de WhatsApp armado adivinando abre el chat de otra
persona.
"""
from django.test import SimpleTestCase

from catus.services.contacto import contacto, link_de_llamada, link_de_whatsapp


class WhatsappTest(SimpleTestCase):

    def test_las_formas_en_que_se_escribe_un_celular_de_buenos_aires(self):
        for escrito in ("11 5555-4444", "1155554444", "011 5555 4444", "15 5555-4444", "011 15 5555-4444",
                        "+54 9 11 5555 4444", "54 11 5555 4444", "549 11 5555-4444", "(11) 5555.4444"):
            with self.subTest(escrito=escrito):
                self.assertEqual(link_de_whatsapp(escrito), "https://wa.me/5491155554444")

    def test_un_celular_del_interior_con_su_codigo_de_area(self):
        self.assertEqual(link_de_whatsapp("0351 555-4444"), "https://wa.me/5493515554444")
        self.assertEqual(link_de_whatsapp("+54 9 351 555 4444"), "https://wa.me/5493515554444")

    def test_de_otro_pais_va_como_lo_escribieron(self):
        self.assertEqual(link_de_whatsapp("+598 99 123 456"), "https://wa.me/59899123456")

    def test_si_no_se_puede_saber_el_numero_completo_no_hay_link(self):
        for escrito in ("5555-4444", "", None, "no tengo", "0351 15 555 4444", "123", "1" * 20):
            with self.subTest(escrito=escrito):
                self.assertIsNone(link_de_whatsapp(escrito))


class LinksTest(SimpleTestCase):

    def test_al_link_solo_llegan_digitos(self):
        self.assertEqual(link_de_llamada("11 5555-4444"), "tel:1155554444")
        self.assertEqual(link_de_llamada("+54 9 11 5555 4444"), "tel:+5491155554444")

        for escrito in ('11 5555-4444" onclick="alert(1)', "javascript:alert(1)//1155554444", "<script>1155554444</script>"):
            with self.subTest(escrito=escrito):
                self.assertRegex(link_de_llamada(escrito), r"^tel:\+?\d+$")
                whatsapp = link_de_whatsapp(escrito)
                if whatsapp is not None:
                    self.assertRegex(whatsapp, r"^https://wa\.me/\d+$")

    def test_un_mail_que_no_es_un_mail_no_arma_link(self):
        datos = contacto("11 5555-4444", "javascript:alert(1)")
        self.assertIsNone(datos["mail"])
        self.assertEqual(datos["llamada"], "tel:1155554444")

    def test_el_mail_valido_arma_el_mailto(self):
        self.assertEqual(contacto("", " ana@example.com ")["mail"], "mailto:ana@example.com")

    def test_sin_datos_no_hay_ningun_link(self):
        self.assertEqual(contacto(None, None), {"whatsapp": None, "llamada": None, "mail": None})
