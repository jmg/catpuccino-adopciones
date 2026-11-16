import ast

from catus.services.base import BaseService
from catus.models import ChatGTPResponse
from catus.utils import DescargaRechazada, descargar, es_url_de_instagram
from django.conf import settings
import openai
import json
import re
from bs4 import BeautifulSoup


class GPTService(BaseService):

    #la página de un post de Instagram pesa menos de 1 MB
    MAX_POST_BYTES = 5 * 1024 * 1024

    #El pedido web espera esta llamada, y el worker corta a los 30s. Sin timeout el SDK
    #espera 600s (y el 1.x además reintenta dos veces): el rescatista pegaba el link y se
    #comía un 502 en vez de un error. Lo mismo que hace ModeracionService.
    TIMEOUT_OPENAI = 12

    #gpt-3.5-turbo ya no existe para las cuentas de OpenAI: la API contestaba
    #InvalidRequestError y "Obtener datos desde Instagram" fallaba siempre, con un
    #"No pudimos leer ese post" que no decía por qué.
    MODELO = "gpt-4o-mini"

    def _get_html_title_and_images(self, url):

        #el link lo pega el rescatista y el server lo va a buscar: solo instagram.com,
        #por https, y lo mismo cada redirect. Sin esto se le podía hacer pedir al server
        #cualquier dirección, internas incluidas.
        try:
            html_code = descargar(url, es_url_de_instagram, self.MAX_POST_BYTES)
        except DescargaRechazada:
            raise ValueError("El link tiene que ser de un post de Instagram (https://www.instagram.com/...).")

        html = BeautifulSoup(html_code, 'html.parser')
        title = html.find("meta", property="og:title")

        #instagram devuelve una página sin og:title cuando el post es privado, no existe
        #o pide login: antes era un 500
        if title is None or not title.attrs.get("content"):
            raise ValueError("No pudimos leer ese post. Puede ser privado o no existir.")

        text = title.attrs["content"]

        images = []

        return text, images

    def convert_to_dict(self, response_content):

        data = {}
        for line in response_content.split("\n"):
            if ":" in line:
                attr, value = line.split(":")
                data[attr] = value

        return data

    #formas en que el modelo dice "no sé" cuando el dato no está en el post
    NO_VALUES = ("no", "no se", "no se especifica", "no se menciona", "no corresponde", "no especifica")

    #las frases largas a veces siguen ("no se especifica en el post"), las cortas no
    NO_VALUES_LARGOS = tuple(no_value for no_value in NO_VALUES if len(no_value.split()) >= 3)

    def clean_value(self, value):
        """Vacía el valor si el modelo contestó que no sabe.

        Se compara el valor entero, no por subcadena: buscando subcadenas, un perro
        llamado Bruno o Nono se quedaba sin nombre, y el JS de la carga corta la
        precarga completa cuando falta el nombre, asi que se perdía toda la importación.
        """

        limpio = value.strip().lower().rstrip(".")

        if limpio in self.NO_VALUES or limpio.startswith(self.NO_VALUES_LARGOS):
            return ""

        return value

    def strip_code_fence(self, content):
        """Saca el ```json ... ``` con el que el modelo suele envolver la respuesta.

        Sin esto json.loads falla y se caía al parseo por líneas, que devolvía el
        nombre con comillas incluidas y el tipo equivocado.
        """

        if not content:
            return content

        limpio = content.strip()

        if not limpio.startswith("```"):
            return limpio

        limpio = re.sub(r"^```[a-zA-Z]*\s*", "", limpio)
        limpio = re.sub(r"\s*```$", "", limpio)

        return limpio.strip()

    def parse_data_obj(self, response_content):
        """Interpreta la respuesta del modelo como diccionario, o None."""

        limpio = self.strip_code_fence(response_content)

        try:
            return json.loads(limpio)
        except Exception:
            pass

        try:
            #a veces viene como dict de Python, con comillas simples. literal_eval
            #entiende solo literales: con eval(), cualquiera que escribiera el caption
            #de un post de Instagram podía hacer que el server ejecutara código.
            return ast.literal_eval(limpio)
        except Exception:
            pass

        try:
            return self.convert_to_dict(limpio)
        except Exception:
            return None

    def parse_response(self, response_content):

        data = {}
        data["response"] = response_content

        data_obj = self.parse_data_obj(response_content)

        if not data_obj or not isinstance(data_obj, dict):
            return data

        for attr_name in data_obj.keys():

            attr = attr_name.strip().lower()
            try:
                value = data_obj[attr_name].strip() if data_obj[attr_name] is not None else ""
            except:
                value = ""

            if "nombre" in attr or "animal" in attr:
                if value.endswith("."):
                    value = value[:-1]

                value = self.clean_value(value)
                data["Nombre"] = value

            elif "tipo" in attr:
                if value.endswith("."):
                    value = value[:-1]

                if value.lower() == "perro":
                    value = "P"
                elif value.lower() == "gato":
                    value = "G"
                else:
                    value = "G"

                data["Tipo"] = value

            elif "edad" in attr:
                if value.endswith("."):
                    value = value[:-1]

                value = self.clean_value(value)
                data["Edad"] = value

            elif "descripción" in attr or "descripcion" in attr:

                if value.startswith('"'):
                    value = value[1:]
                if value.endswith('"'):
                    value = value[:-1]
                if value.endswith('".'):
                    value = value[:-2]
                data["Descripcion"] = value

            elif "sexo" in attr:
                if value.endswith("."):
                    value = value[:-1]
                if value.lower() == "macho":
                    value = "M"
                elif value.lower() == "hembra":
                    value = "H"
                else:
                    value = "D"
                data["Sexo"] = value

        return data

    def pull_data_from_ig(self, url, pedido=None):
        """Los datos del animal que trae un post de Instagram.

        `pedido` es la fila de ChatGTPResponse que la vista anota antes de llamar, la que
        cuentan los topes: la respuesta se guarda ahí. Antes se creaba una segunda fila, y
        el tope total del sitio (que cuenta todas) cortaba a las 15 lecturas y no a las 30.
        """

        if not es_url_de_instagram(url):
            raise ValueError("El link tiene que ser de un post de Instagram (https://www.instagram.com/...).")

        prompt = "Si el post es sobre un gato o perro en adopción: Extraer el nombre del animal en adopción, tipo (perro o gato), sexo (se puede deducir del texto, para el resultado usar el valor 'macho' o 'hembra'), edad y descripción (copiarla textualmente sin usar \"). Responder con un objeto JSON. No usar comentarios // en el JSON."

        text, images = self._get_html_title_and_images(url)

        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": text},
        ]

        content = self._preguntar(messages)

        if pedido is not None:
            pedido.chatgpt_response = content
            pedido.save(update_fields=["chatgpt_response"])
        else:
            #la columna es de 255: con MySQL estricto una URL más larga daba DataError
            #después de haberle pagado la llamada a OpenAI
            ChatGTPResponse.objects.create(
                ig_url_for_chatgpt=(url or "")[:255],
                chatgpt_response=content,
            )

        data = self.parse_response(content)
        data["images"] = images

        return data

    def _preguntar(self, messages):
        """La respuesta del modelo. Con el SDK 1.x (openai.OpenAI), el de producción desde
        que se dejó openai 0.28; el 0.x queda mientras alguna imagen lo tenga instalado."""

        #la respuesta copia la descripción del post, y un caption de Instagram tiene a lo
        #sumo 2200 caracteres: con esto alcanza y una respuesta no se dispara
        max_tokens = 1500

        if hasattr(openai, "OpenAI"):

            cliente_kwargs = {
                "api_key": settings.OPENIA_API_KEY,
                "timeout": self.TIMEOUT_OPENAI,
                #el 1.x reintenta dos veces por su cuenta: tres esperas de 12s no entran
                #en los 30s del worker
                "max_retries": 0,
            }
            if settings.OPENIA_API_ORG_ID:
                cliente_kwargs["organization"] = settings.OPENIA_API_ORG_ID

            respuesta = openai.OpenAI(**cliente_kwargs).chat.completions.create(
                model=self.MODELO, messages=messages, max_tokens=max_tokens,
            )
            return respuesta.choices[0].message.content

        openai.organization = settings.OPENIA_API_ORG_ID
        openai.api_key = settings.OPENIA_API_KEY

        respuesta = openai.ChatCompletion.create(
            model=self.MODELO, messages=messages, request_timeout=self.TIMEOUT_OPENAI, max_tokens=max_tokens,
        )
        return respuesta["choices"][0]["message"]["content"]