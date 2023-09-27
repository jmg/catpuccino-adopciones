from catus.services.base import BaseService
from catus.models import ChatGTPResponse
from django.conf import settings
import openai
import json
import re
import instaloader
import requests
from bs4 import BeautifulSoup
import os.path
from pathlib2 import Path


class GPTService(BaseService):

    def _get_html_title_and_images(self, url):

        try:
            L = instaloader.Instaloader(save_metadata=False, quiet=True, compress_json=False)
            #get IG shortcode from url
            regex = r"^(?:https?:\/\/)?(?:www\.)?(?:instagram\.com.*\/p\/)([\d\w\-_]+)(?:\/)?(\?.*)?$"
            code = re.findall(regex, url)[0][0]

            post = instaloader.Post.from_shortcode(L.context, code)
            path = Path(settings.MEDIA_ROOT)
            media_dir = path.joinpath("gallery", "ig", code)

            L.download_post(post, target=media_dir)

            text = post.caption
            images = []

            for file in os.listdir(media_dir):
                if file.endswith(".jpg") or file.endswith(".png") or file.endswith(".jpeg") or file.endswith(".gif") or file.endswith(".mp4") or file.endswith(".webp"):
                    images.append("{}/gallery/ig/{}/{}".format(settings.SSL_HOST, code, file))
        except:
            response = requests.get(url)
            html_code = response.content

            html = BeautifulSoup(html_code, 'html.parser')
            title = html.find("meta", property="og:title")
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

    def clean_value(self, value):

        no_values = ["no", "no se", "no se especifica", "no se menciona", "no corresponde", "no especifica"]
        for no_value in no_values:
            if no_value in value.lower():
                value = ""

        return value

    def parse_response(self, response_content):

        data = {}
        data["response"] = response_content

        try:
            data_obj = json.loads(response_content)
        except:
            try:
                #it can be a python dict
                data_obj = eval(response_content)
            except:
                #try parsing by \n
                try:
                    data_obj = self.convert_to_dict(response_content)
                except:
                    data_obj = None

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

    def pull_data_from_ig(self, url):

        openai.organization = settings.OPENIA_API_ORG_ID
        openai.api_key = settings.OPENIA_API_KEY

        model = "gpt-3.5-turbo"
        prompt = "Si el post es sobre un gato o perro en adopción: Extraer el nombre del animal en adopción, tipo (perro o gato), sexo (se puede deducir del texto, para el resultado usar el valor 'macho' o 'hembra'), edad y descripción (copiarla textualmente sin usar \"). Responder con un objeto JSON. No usar comentarios // en el JSON."

        text, images = self._get_html_title_and_images(url)

        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": text},
        ]

        response = openai.ChatCompletion.create(model=model, messages=messages)
        content = response["choices"][0]["message"]["content"]

        ChatGTPResponse.objects.create(
            ig_url_for_chatgpt=url,
            chatgpt_response=content,
        )

        data = self.parse_response(content)
        data["images"] = images

        return data