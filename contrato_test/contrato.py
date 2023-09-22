import sys
sys.path.append("..")

from catus.services.contrato import generate_contrato_pdf
from dateutil.parser import parse


class ContratoPersona():

    persona_nombre = "juan"
    persona_dni = "34049568"
    persona_fecha_nacimiento = parse("03/09/1988")
    persona_ocupacion = "programados"
    persona_email = "jmg.utn"
    persona_celular = "55555555"
    persona_direccion = "san pedro 5309 manzana 4 edificio 10 calle 432423 streer 3232 avenue 89"
    persona_localidad = "local"
    persona_instagram = "insta"
    persona_facebook = "facebok"


class Pet():

    tipo = "G"


class Contrato():

    def get_tipo(self):

        return self.gato.tipo if self.gato is not None else "G"

    adoptante = ContratoPersona()
    gato = Pet()

    gato_nombre = "willy"
    gato_sexo = "M"
    gato_color = "naranja"
    gato_fecha_nacimiento = parse("03/05/2019")
    gato_edad = "1 año"

    gato_vacunacion_antirabica = parse("02/02/20")
    gato_vacunacion_antirabica_fecha = parse("03/02/20")

    gato_vacunacion_triple_1_dosis = True
    gato_vacunacion_triple_1_dosis_fecha = parse("04/02/20")

    gato_vacunacion_triple_2_dosis = True
    gato_vacunacion_triple_2_dosis_fecha = parse("05/02/20")

    gato_castrado = True
    gato_castrado_fecha = parse("06/02/20")
    gato_castracion_fecha_futura = parse("06/02/22")

    #gato_castrado = False
    #gato_castrado_fecha = None

    gato_desparasitado = True
    gato_desparasitado_fecha = parse("07/02/20")

    gato_desparasitado_2 = True
    gato_desparasitado_fecha_2 = parse("07/02/20")

    gato_pipeta_antipulgas = True
    gato_pipeta_antipulgas_fecha = parse("08/02/20")

    gato_alimento = "Purina Excellent de Pollo y Arroz y Pescado Premium 10KG"

    gato_cuidados_especiales = """Wrap a single paragraph of text, returning a list of wrapped lines.

    Reformat the single paragraph in 'text' so it fits in lines of no
    more than 'width' columns, and return a list of wrapped lines.  By
    default, tabs in 'text' are expanded with string.expandtabs(), and
    all other whitespace characters (including newline) are converted to
    space.  See TextWrapper class for available keyword args to customize
    wrapping behaviour."""

    gato_vacunacion_antirabica_notas = "dasdas das dsdas asd sad asdasdas 10/09/20 dasda dslas fsdf fdf fdsss"
    gato_desparasitado_notas = "gato_desparasitado_notas estas son notas largas prueba de como se veria en 2 lineas differentes sin que se superpongan"
    gato_desparasitado_producto = "antiparasitario gatos 2.3"

    gato_pipeta_antipulgas_notas = "gato_pipeta_antipulgas_notas estas son notas largas prueba de como se veria en 2 lineas differentes sin que se superpongan"
    gato_pipeta_antipulgas_producto = "frontline 2.0"

    gato_castrado_notas = "gato_castrado_notas fhsdjfhd sfjksdfh sdjkfh sdjk fdfjjkd sdfklfj skl fd sdfds sdff sd dfds fdsf dsfsdfdd"
    gato_vacunacion_triple_2_dosis_notas = "gato_vacunacion_triple_2_dosis"
    gato_vacunacion_triple_1_dosis_notas = "gato_vacunacion_triple_1_dosis"

    contrato_fecha = parse("09/02/20")
    contrato_aceptado = True

    miembro_adopcion_nombre = "Juan Manuel Garcia"
    hash = "1"

    #PERROS
    perro_vacunacion_quintuple_1_dosis = True
    perro_vacunacion_quintuple_1_dosis_fecha = parse("04/02/20")
    perro_vacunacion_quintuple_1_dosis_notas = "perro_vacunacion_5tuple_2_dosis"

    perro_vacunacion_quintuple_2_dosis = True
    perro_vacunacion_quintuple_2_dosis_fecha = parse("05/02/20")
    perro_vacunacion_quintuple_2_dosis_notas = "perro_vacunacion_5tuple_2_dosis"

    perro_vacunacion_sextuple_1_dosis = True
    perro_vacunacion_sextuple_1_dosis_fecha = parse("04/02/20")
    perro_vacunacion_sextuple_1_dosis_notas = "perro_vacunacion_6tuple_notas"


contrato = Contrato()
generate_contrato_pdf(contrato, is_test=True)