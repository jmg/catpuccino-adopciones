"""Las columnas por las que se busca en cada pedido tienen índice.

/formularios/<hash>/, /contrato/<hash>/ y /<handle>/ buscaban por columnas sin índice, así
que cada visita recorría la tabla entera (migración 0042). Si alguien rehace el campo y se
pierde el db_index, makemigrations no se queja de nada: se nota recién en producción.
"""
from django.test import SimpleTestCase

from catus.models import CatusUser, Contrato, EstadoFormulario


class IndicesTest(SimpleTestCase):

    def test_el_hash_del_formulario_tiene_indice(self):
        self.assertTrue(EstadoFormulario._meta.get_field("hash").db_index)

    def test_el_hash_del_contrato_tiene_indice(self):
        self.assertTrue(Contrato._meta.get_field("hash").db_index)

    def test_el_handle_tiene_indice(self):
        self.assertTrue(CatusUser._meta.get_field("handle").db_index)
