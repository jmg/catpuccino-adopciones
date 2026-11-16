"""Completa Animal.edad_en_meses en los animales que ya estaban cargados.

La portada filtra por Cachorros (menos de 12 meses) y Adultos con edad_en_meses, que casi
nadie completaba: desde ahora Animal.save() lo estima del texto de la edad
(catus/services/edad.py), y esto lo hace una vez para los que ya existen. Solo toca los
que no tienen un valor; los que no se pueden estimar quedan vacíos.

El código de abajo es una COPIA CONGELADA de catus/services/edad.py tal como estaba al
escribir esta migración, y no se importa el módulo vivo: una migración tiene que hacer
siempre lo mismo, aunque el parser cambie después. No hace falta mantenerla al día.
"""
import math
import re
import unicodedata
from datetime import date

from django.db import migrations

#cuántos meses es cada unidad (un mes de 30,44 días en promedio)
MESES_POR_UNIDAD = {"ano": 12.0, "mes": 1.0, "semana": 7 / 30.4375, "dia": 1 / 30.4375}

#para sumar solo hacia unidades más chicas: "1 año y 2 meses", no "2 meses y 1 año"
TAMANO_DE_UNIDAD = {"ano": 4, "mes": 3, "semana": 2, "dia": 1}

#ya sin tildes ni eñes: "años" llega como "anos"
UNIDADES = {
    "ano": "ano", "anos": "ano", "anito": "ano", "anitos": "ano",
    "mes": "mes", "meses": "mes", "mesecito": "mes", "mesecitos": "mes", "m": "mes",
    "semana": "semana", "semanas": "semana", "semanita": "semana", "semanitas": "semana",
    "sem": "semana",
    "dia": "dia", "dias": "dia", "diita": "dia", "diitas": "dia", "d": "dia",
}

#pegadas al número ("7m", "2a") son unidades; sueltas, "a" es "de 2 a 3 años"
UNIDADES_PEGADAS = dict(UNIDADES, a="ano")

#"1/2 año" es medio año; "1/2 años", de uno a dos. "mes" termina en s y es singular.
EN_SINGULAR = {"ano", "anito", "mes", "mesecito", "semana", "semanita", "dia", "diita"}

NUMEROS_EN_LETRAS = {
    "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
    "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "quince": 15,
    "veinte": 20, "treinta": 30, "medio": 0.5, "media": 0.5,
}

#lo que une un rango: "6/7", "4-5", "2 a 3", "3 y 4", "2 o 3", "1 al 2"
UNEN_UN_RANGO = {"/", "-", "a", "al", "y", "o"}

#lo que une las partes de una edad: "1 año y 2 meses", "2 meses, 3 semanas"
UNEN_PARTES = {"y", ",", "con"}

NOMBRES_DE_MES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11,
    "diciembre": 12,
}

#nada que viva tanto: un número así es un error de tipeo, no una edad
MAXIMO_DE_MESES = 30 * 12

#el texto es corto (la columna es de 255), pero se corta igual: corre en cada save
LARGO_MAXIMO = 255

FECHA_COMPLETA = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4}|\d{2})\b")
MES_Y_ANIO = re.compile(r"\b(\d{1,2})[/.-](\d{4})\b")
NOMBRE_DE_MES_Y_ANIO = re.compile(r"\b(" + "|".join(NOMBRES_DE_MES) + r")\s+(?:de\s+|del\s+)?(\d{4})\b")

TOKEN = re.compile(r"(\d+(?:[.,]\d+)?)([a-z]*)|([a-z]+)|([/+,-])")

#sin número ni fecha: lo que dicen las palabras, de la más específica a la más general
PALABRAS = (
    (re.compile(r"\brecien nacid"), 0),
    (re.compile(r"\bbeb[eia]"), 2),
    (re.compile(r"\bcachorr"), 6),
    (re.compile(r"\b(senior|geronte|ancian|abuel|viejit|mayor\b)"), 96),
    (re.compile(r"\badult"), 24),
)


def _normalizar(texto):
    """En minúscula y sin tildes: "AÑO" y "año" son "ano"."""

    texto = unicodedata.normalize("NFD", texto.lower())
    return "".join(letra for letra in texto if unicodedata.category(letra) != "Mn")


def _meses_desde(anio, mes, dia, hoy):

    if anio < 100:
        anio += 2000

    if not (1 <= mes <= 12 and 1 <= dia <= 31):
        return None

    meses = (hoy.year - anio) * 12 + (hoy.month - mes) - (1 if hoy.day < dia else 0)
    if meses < 0 or meses > MAXIMO_DE_MESES:
        return None

    return meses


def _desde_una_fecha(texto, hoy):
    """Los meses desde una fecha de nacimiento escrita en el texto, o None."""

    fecha = FECHA_COMPLETA.search(texto)
    if fecha:
        dia, mes, anio = (int(parte) for parte in fecha.groups())
        return _meses_desde(anio, mes, dia, hoy)

    fecha = MES_Y_ANIO.search(texto)
    if fecha:
        mes, anio = (int(parte) for parte in fecha.groups())
        return _meses_desde(anio, mes, 1, hoy)

    fecha = NOMBRE_DE_MES_Y_ANIO.search(texto)
    if fecha:
        return _meses_desde(int(fecha.group(2)), NOMBRES_DE_MES[fecha.group(1)], 1, hoy)

    return None


def _tokens(texto):
    """El texto como una lista de (tipo, valor, plural): números, unidades y palabras."""

    tokens = []
    for numero, pegado, palabra, signo in TOKEN.findall(texto):

        if numero:
            tokens.append(("num", float(numero.replace(",", ".")), False))
            if pegado in UNIDADES_PEGADAS:
                tokens.append(("unidad", UNIDADES_PEGADAS[pegado], pegado not in EN_SINGULAR))
            elif pegado:
                tokens.append(("palabra", pegado, False))

        elif palabra:
            if palabra in NUMEROS_EN_LETRAS:
                tokens.append(("num", float(NUMEROS_EN_LETRAS[palabra]), False))
            elif palabra in UNIDADES:
                tokens.append(("unidad", UNIDADES[palabra], palabra not in EN_SINGULAR))
            else:
                tokens.append(("palabra", palabra, False))

        else:
            tokens.append(("signo", signo, False))

    return tokens


def _es(tokens, i, tipo, valores=None):

    #i puede quedar en -1 al mirar para atrás: tokens[-1] sería el último, no "nada"
    if i < 0 or i >= len(tokens) or tokens[i][0] != tipo:
        return False

    return valores is None or tokens[i][1] in valores


def _primera_cantidad(tokens, i):
    """La cantidad que arranca en tokens[i]: (meses, unidad, índice siguiente) o None."""

    if _es(tokens, i, "num"):

        #"6/7 meses", "2 a 3 años": el punto medio. "1/2 año", en singular, es medio año.
        if (_es(tokens, i + 1, "signo", UNEN_UN_RANGO) or _es(tokens, i + 1, "palabra", UNEN_UN_RANGO)) \
                and _es(tokens, i + 2, "num") and _es(tokens, i + 3, "unidad"):
            desde, hasta, (_, unidad, plural) = tokens[i][1], tokens[i + 2][1], tokens[i + 3]
            if tokens[i + 1][1] == "/" and not plural and desde < hasta and hasta in (2, 3, 4):
                cantidad = desde / hasta
            elif tokens[i + 1][1] == "y" and hasta == 0.5:
                #"1 y medio años" no es un rango
                cantidad = desde + hasta
            else:
                cantidad = (desde + hasta) / 2
            return cantidad * MESES_POR_UNIDAD[unidad], unidad, i + 4

        if _es(tokens, i + 1, "unidad"):
            unidad = tokens[i + 1][1]
            return tokens[i][1] * MESES_POR_UNIDAD[unidad], unidad, i + 2

        return None

    #"año y medio", "mes y medio": la unidad sola, en singular, es una
    if _es(tokens, i, "unidad") and not tokens[i][2] and not _es(tokens, i - 1, "num") \
            and _es(tokens, i + 1, "palabra", {"y"}) and _es(tokens, i + 2, "num", {0.5}):
        unidad = tokens[i][1]
        return MESES_POR_UNIDAD[unidad], unidad, i + 1

    return None


def _sumar_las_partes(tokens, j, meses, unidad):
    """Suma lo que sigue a una cantidad: "y 2 meses", ", 3 semanas", "y medio"."""

    while True:
        k = j
        while _es(tokens, k, "palabra", UNEN_PARTES) or _es(tokens, k, "signo", UNEN_PARTES):
            k += 1

        if not _es(tokens, k, "num"):
            return meses

        if _es(tokens, k + 1, "unidad") and TAMANO_DE_UNIDAD[tokens[k + 1][1]] < TAMANO_DE_UNIDAD[unidad]:
            unidad = tokens[k + 1][1]
            meses += tokens[k][1] * MESES_POR_UNIDAD[unidad]
            j = k + 2
            continue

        #"y medio": de la unidad anterior
        if tokens[k][1] == 0.5 and k > j and not _es(tokens, k + 1, "unidad"):
            meses += 0.5 * MESES_POR_UNIDAD[unidad]
            j = k + 1
            continue

        return meses


def _desde_una_cantidad(tokens):
    """Los meses de la primera edad escrita con números o con letras, o None."""

    for i in range(len(tokens)):

        cantidad = _primera_cantidad(tokens, i)
        if cantidad is None:
            continue

        meses, unidad, siguiente = cantidad
        meses = _sumar_las_partes(tokens, siguiente, meses, unidad)

        #"menos de un año" es un cachorro; "casi 2 años", 23 meses
        if _es(tokens, i - 1, "palabra", {"casi"}) or \
                (_es(tokens, i - 1, "palabra", {"de"}) and _es(tokens, i - 2, "palabra", {"menos"})):
            meses = max(meses - 1, 0)

        if not math.isfinite(meses) or meses > MAXIMO_DE_MESES:
            return None

        #el redondeo hacia abajo con un margen: 1,5 años son 18 meses aunque la cuenta dé 17,999…
        return int(math.floor(meses + 1e-9))

    return None


def estimar_meses(edad, hoy=None):
    """Los meses que tiene un animal según el texto de su edad, o None si no se sabe."""

    if not edad or not isinstance(edad, str):
        return None

    if hoy is None:
        hoy = date.today()

    texto = _normalizar(edad[:LARGO_MAXIMO])

    #las fechas se sacan antes de buscar cantidades: "15/03/2024" no es un rango
    sin_fechas = NOMBRE_DE_MES_Y_ANIO.sub(" ", MES_Y_ANIO.sub(" ", FECHA_COMPLETA.sub(" ", texto)))

    meses = _desde_una_cantidad(_tokens(sin_fechas))
    if meses is None:
        meses = _desde_una_fecha(texto, hoy)

    if meses is None:
        for patron, meses_de_la_palabra in PALABRAS:
            if patron.search(texto):
                meses = meses_de_la_palabra
                break

    if meses is None or meses < 0 or meses > MAXIMO_DE_MESES:
        return None

    return meses


def completar_edad_en_meses(apps, schema_editor):

    Animal = apps.get_model("catus", "Animal")
    hoy = date.today()

    estimados = []
    sin_meses = Animal.objects.filter(edad_en_meses__isnull=True).exclude(edad__isnull=True).exclude(edad="")
    for animal in sin_meses.only("id", "edad").iterator(chunk_size=500):
        meses = estimar_meses(animal.edad, hoy)
        if meses is not None:
            animal.edad_en_meses = meses
            estimados.append(animal)

    Animal.objects.bulk_update(estimados, ["edad_en_meses"], batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ("catus", "0045_indices_de_busqueda"),
    ]

    operations = [
        #al revés no hace nada: no se sabe cuáles completó esta y cuáles una persona
        migrations.RunPython(completar_edad_en_meses, migrations.RunPython.noop, elidable=True),
    ]
