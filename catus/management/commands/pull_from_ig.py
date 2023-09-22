from django.core.management.base import BaseCommand
from catus.services.mail import MailService
from catus.models import Animal, FacebookAccount
from catus.services.facebook import FacebookApiService
from catus.services.cache import CacheService
import openai
import json
import tiktoken
from django.conf import settings


class Command(BaseCommand):

    def num_tokens_from_messages(self, messages, model="gpt-3.5-turbo-0301"):
        """Returns the number of tokens used by a list of messages."""
        try:
            encoding = tiktoken.encoding_for_model(model)
        except KeyError:
            encoding = tiktoken.get_encoding("cl100k_base")
        if model == "gpt-3.5-turbo-0301":  # note: future models may deviate from this
            num_tokens = 0
            for message in messages:
                num_tokens += 4  # every message follows <im_start>{role/name}\n{content}<im_end>\n
                for key, value in message.items():
                    num_tokens += len(encoding.encode(value))
                    if key == "name":  # if there's a name, the role is omitted
                        num_tokens += -1  # role is always required and always 1 token
            num_tokens += 2  # every reply is primed with <im_start>assistant
            return num_tokens
        else:
            raise NotImplementedError(f"""num_tokens_from_messages() is not presently implemented for model {model}.
        See https://github.com/openai/openai-python/blob/main/chatml.md for information on how messages are converted to tokens.""")

    def handle(self, *args, **options):

        account = FacebookAccount.objects.all().first()
        LIMIT = 10
        USE_CACHE = False

        if USE_CACHE:
            posts = CacheService().get("ig-posts")
            if not posts:
                posts = FacebookApiService.get_all_posts(account, limit=LIMIT)
                CacheService().set("ig-posts", json.dumps(posts))
            else:
                posts = json.loads(posts)
        else:
            posts = FacebookApiService.get_all_posts(account, limit=LIMIT)

        openai.organization = settings.OPENIA_API_ORG_ID
        openai.api_key = settings.OPENIA_API_KEY

        animals = []
        for i, post in enumerate(posts):

            text = post.get("caption", "").lower()

            model = "gpt-3.5-turbo"
            prompt = "Si el post es sobre un gato o perro en adopción: Extraer el nombre del animal en adopción, tipo, sexo, edad y descripción. Sino responder: no corresponde"

            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": text},
            ]

            print (self.num_tokens_from_messages(messages))
            response = openai.ChatCompletion.create(model=model, messages=messages)

            content = response["choices"][0]["message"]["content"]
            lines = content.split("\n")

            data = {}
            for line in lines:
                parts = line.split(":")
                if len(parts) == 2:
                    data[parts[0].strip()] = parts[1].strip()

            data["response"] = content
            animals.append(data)

            print (data)

            if i > 10:
                break

        print (animals)