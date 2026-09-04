from ..models import Animal, FacebookAccount
from pyfb.pyfb import Pyfb
from django.conf import settings
import json
import logging
import requests
import urllib
import time


#todo esto se enteraba de las cosas con print(), o sea que la salida se la quedaba el cron y
#no quedaba en ningún lado: de una corrida sólo se sabía lo que crasheaba y llegaba a Sentry
logger = logging.getLogger(__name__)


class MediaError(Exception):
    """Instagram marcó el contenedor como fallado: reintentar no lo va a arreglar."""


class FacebookApiService:

    #Instagram no acepta más de 10 fotos en un carrusel (ni menos de 2)
    MAX_IMAGENES_POR_POST = 10

    def __init__(self, token=None, account=None, raw_data=False):

        facebook = Pyfb(settings.FACEBOOK_APP_ID, raw_data=raw_data)

        if account:
            token = account.facebook_token

        facebook.set_access_token(token)

        self.facebook = facebook
        self.account = account

    @classmethod
    def get_expires_in(cls, data):

        if not "expire_in" in data and not "expires_in" in data:
            expire_in = 60 * 24 * 60 * 60
        else:
            expire_in = data.get("expire_in")
            if not expire_in:
                expire_in = data.get("expires_in")

        return expire_in

    @classmethod
    def get_long_lived_token(cls, token):

        params = "grant_type=fb_exchange_token&client_id={}&client_secret={}&fb_exchange_token={}".format(settings.FACEBOOK_APP_ID, settings.FACEBOOK_APP_SECRET, token)
        url = "https://graph.facebook.com/v4.0/oauth/access_token?{}".format(params)
        response = requests.get(url)

        data = response.json()
        if "error" in data:
            raise Exception(data["error"]["message"])

        if not "access_token" in data:
            raise Exception(u"{}".format(data))

        expire_in = cls.get_expires_in(data)
        return data["access_token"], expire_in

    @classmethod
    def get_long_lived_token_instagram(cls, token):

        url = "https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token&access_token={}".format(token)
        response = requests.get(url)

        data = response.json()
        if "error" in data:
            raise Exception(data["error"]["message"])

        if not "access_token" in data:
            raise Exception(u"{}".format(data))

        expire_in = cls.get_expires_in(data)
        return data["access_token"], expire_in

    def get_instagram_accounts(self):

        account_names = []
        instagram_account_names = []
        account_data = {}
        accounts = self.facebook.request("me/accounts?fields=instagram_business_account,name,username,about,website,picture")

        for account in accounts["data"]:
            if "instagram_business_account" in account:
                instagram_business_account_id = account["instagram_business_account"]["id"]
                instagram_account_names.append((account["id"], account["name"]))
            else:
                instagram_business_account_id = None
                account_names.append((account["id"], account["name"]))

            account_data[account["id"]] = {
                "full_name": account.get("name"),
                "username": account.get("username"),
                "bio": account.get("about"),
                "website": account.get("website"),
                "profile_picture": account.get("picture", {}).get("data", {}).get("url"),
                "instagram_account_id": instagram_business_account_id,
                "remote_id": instagram_business_account_id,
            }

        return account_names, instagram_account_names, account_data

    #10 intentos de 2 s son ~20 s por contenedor. Eran 30 de 2 s, o sea hasta un minuto
    #por foto, y un carrusel es un contenedor por foto más uno del carrusel: con 10 fotos
    #la publicación se iba a más de diez minutos, mucho más de lo que aguanta el cron (y de
    #los 30 s que le da el worker a /tools/publish/)
    @classmethod
    def wait_for_media_ready(cls, service, creation_id, max_attempts=10, wait_seconds=2):
        """Espera a que Instagram termine de procesar el contenedor.

        Sólo devuelve True con un FINISHED de Instagram en la mano. Antes, en el último
        intento, un status_code None -o sea "no sé en qué estado quedó"- dormía un segundo
        y devolvía True igual: se publicaba a ciegas algo que Instagram todavía no había
        procesado.
        """

        #se piden los dos campos: con fields=status_code el status nunca venía, así que
        #cuando Instagram contestaba ERROR el motivo se perdía y quedaba "Unknown error"
        url = "{}?fields=status_code,status".format(creation_id)

        ultimo_estado = None
        ultimo_error = None

        for attempt in range(max_attempts):

            try:
                response = service.facebook.request(url)
                ultimo_estado = response.get("status_code")

                if ultimo_estado == "FINISHED":
                    return True

                if ultimo_estado == "ERROR":
                    motivo = response.get("status") or response.get("error_message") or "sin motivo"
                    raise MediaError("Instagram falló el contenedor {}: {}".format(creation_id, motivo))

            except MediaError:
                #Instagram ya dijo que falló: el except de abajo lo tomaba como un error
                #cualquiera y seguía reintentando 30 veces, o sea un minuto por foto
                raise

            except Exception as e:
                error_str = str(e)
                if "Media ID is not available" in error_str or "does not exist" in error_str.lower():
                    raise Exception("Media container {} is not available: {}".format(creation_id, error_str))

                ultimo_error = error_str
                logger.warning("No se pudo consultar el contenedor %s: %s", creation_id, error_str)

            if attempt < max_attempts - 1:
                time.sleep(wait_seconds)

        #ni FINISHED ni ERROR: no sabemos en qué quedó el contenedor, y publicar sin saberlo
        #es publicar a ciegas. Falla con lo último que contestó Instagram para que se vea.
        detalle = "quedó en estado '{}'".format(ultimo_estado)
        if ultimo_error:
            detalle = "{} (último error: {})".format(detalle, ultimo_error)

        raise Exception(
            "El contenedor {} no llegó a FINISHED después de {} intentos: {}. No se publicó.".format(
                creation_id, max_attempts, detalle,
            )
        )

    @classmethod
    def publish(cls, animal, ig_text):

        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(ig_text)
            ig_text = soup.text
        except:
            pass

        #en local se reemplazaba la imagen por una URL fija de otro sitio, pero se
        #publicaba igual en la cuenta real de la organización: probar la integración
        #desde una máquina de desarrollo dejaba un post de verdad en Instagram
        if settings.ENV == "LOCAL":
            return "ENV=LOCAL: no se publica. Se hubiera publicado '{}' con el texto:\n{}".format(
                animal.nombre, ig_text,
            )

        account = FacebookAccount.objects.all().first()
        if account is None:
            return "No hay ninguna cuenta de Instagram vinculada."

        service = FacebookApiService(account=account)

        #create elements of post
        #lo que se sube es image_for_instagram, que se genera aparte en /tools/makeimages/:
        #una foto agregada después de generarlas no la tiene, y el .url reventaba recién
        #adentro de publish_*, cuando ya habíamos subido contenedores a Instagram
        images = [image for image in animal.get_images() if image.image_for_instagram]
        if not images:
            return "{} no tiene fotos con la imagen de Instagram generada (se generan en /tools/makeimages/).".format(animal.nombre)

        #el truncado estaba escondido en un images[0:10] adentro de publish_multiple_images:
        #con 11 fotos la 11 desaparecía del post y no se enteraba nadie, ni el log ni la
        #pantalla de /tools/publish/, que contestaba "Publicado!" igual
        aviso = ""
        if len(images) > cls.MAX_IMAGENES_POR_POST:
            aviso = " Instagram acepta hasta {} fotos por post: de las {} de {} quedaron afuera las últimas {}.".format(
                cls.MAX_IMAGENES_POR_POST, len(images), animal.nombre, len(images) - cls.MAX_IMAGENES_POR_POST,
            )
            logger.warning("%s tiene %s fotos y sólo se publican %s", animal.nombre, len(images), cls.MAX_IMAGENES_POR_POST)
            images = images[:cls.MAX_IMAGENES_POR_POST]

        #El candado contra el post duplicado vive acá, que es el embudo por el que pasan los
        #dos caminos: el cron y el botón "Publicar" de /tools/publish/. El reclamo del cron
        #sólo se defiende de otra corrida del cron, así que apretar el botón mientras una
        #corrida subía las fotos del mismo animal dejaba dos posts iguales en la cuenta de
        #la organización. Se marca publicado ANTES de tocar Graph: es un test-and-set, así
        #que de dos que entran juntos actualiza una fila uno solo.
        #No se toca instagram_intentos ni instagram_ultimo_intento: esos son del reclamo del
        #cron, que ya corrió antes de llegar hasta acá, y sumarles otro intento le comería
        #a cada animal la mitad de los reintentos y le correría el backoff.
        reclamados = Animal.objects.filter(id=animal.id, instagram_publicado=False).update(
            instagram_publicado=True,
        )

        if reclamados != 1:
            logger.warning("No se publica %s: ya está publicado o lo está publicando otro", animal.nombre)
            return "{} ya está publicado o lo está publicando otra corrida.".format(animal.nombre)

        try:
            if len(images) > 1:
                response_data = cls.publish_multiple_images(service, account, images, ig_text)
            else:
                response_data = cls.publish_one_image(service, account, images, ig_text)

        except Exception as e:
            #no salió nada: se suelta el reclamo para que el animal vuelva a la cola. Sólo
            #instagram_publicado, que es lo único que escribió el reclamo.
            Animal.objects.filter(id=animal.id).update(instagram_publicado=False)

            #fallo esperado de la API: va a warning y sin exc_info, porque los eventos ERROR
            #de Sentry se llevan puesta la cookie de sesión
            error = cls.show_error(e)
            logger.warning("No se pudo publicar %s en Instagram: %s", animal.nombre, error)
            return error

        #el post ya está arriba y no se puede deshacer: se guarda antes de pedir el
        #permalink. Cualquier corte entre publicar y guardar (en /tools/publish/ el worker
        #corta a los 30 s) dejaba el animal como no publicado y el cron lo volvía a
        #publicar en la corrida siguiente, duplicando el post.
        #En el mismo save se apagan la marca de listo y la agenda del posteo automático,
        #que quedaban puestas para siempre. En el admin los cuatro checks son editables y
        #destildar "publicado" es el gesto obvio para rehacer un post: con la marca prendida
        #la corrida siguiente del cron lo publicaba DE NUEVO, pisaba instagram_post_id y el
        #post viejo quedaba huérfano, sin forma de recibir después el comentario de
        #adoptado. Y con la agenda vencida todavía puesta el post duplicado volvía por la
        #puerta de al lado: preparar_publicaciones levantaba al animal por esa fecha y le
        #prendía la marca de nuevo.
        animal.instagram_publicado = True
        animal.instagram_listo_para_publicar = False
        animal.instagram_programado_para = None
        animal.instagram_post_id = response_data["id"]
        animal.save(update_fields=[
            "instagram_publicado", "instagram_listo_para_publicar",
            "instagram_programado_para", "instagram_post_id",
        ])

        #el permalink es sólo un link y update_post_id lo puede completar después
        animal.instagram_media_url = cls.get_media_url(service, response_data)["url"]
        animal.save(update_fields=["instagram_media_url"])

        logger.info("Publicado %s en Instagram: %s", animal.nombre, animal.instagram_post_id)

        return "Publicado!{}".format(aviso)

    @classmethod
    def publish_one_image(cls, service, account, images, ig_text):

        image = images[0]

        image_url = "{}{}".format(settings.SSL_HOST, image.image_for_instagram.url)

        url = "{}/media".format(
            account.business_account_id,
        )

        data = {
            "image_url": image_url,
            "caption": ig_text,
            "locale": "en_us",
        }

        creation_response = service.facebook.request(url, **data)
        creation_id = creation_response["id"]

        # Wait for media to be ready before publishing
        cls.wait_for_media_ready(service, creation_id)

        #publish the post
        url = "{}/media_publish".format(
            account.business_account_id,
        )

        data = {
            "creation_id" : creation_id,
            "locale": "en_us",
        }

        response = service.facebook.request(url, **data)

        #devuelve la respuesta de media_publish tal cual: el permalink lo pide publish()
        #después de guardar, para no perder el post si falla el pedido del link
        return response

    @classmethod
    def publish_multiple_images(cls, service, account, images, ig_text):

        elements = []

        for image in images[0:cls.MAX_IMAGENES_POR_POST]:

            image_url = "{}{}".format(settings.SSL_HOST, image.image_for_instagram.url)

            url = "{}/media".format(
                account.business_account_id,
            )

            #sin is_carousel_item el contenedor se crea como posteo suelto: Graph lo acepta
            #igual, pero es una foto sola subida a la cuenta, no un hijo del carrusel
            data = {
                "image_url": image_url,
                "is_carousel_item": "true",
                "locale": "en_us",
            }

            image_creation_response = service.facebook.request(url, **data)
            image_creation_id = image_creation_response["id"]

            # Wait for each image media to be ready
            cls.wait_for_media_ready(service, image_creation_id)

            elements.append(image_creation_id)

        #create container of elements
        url = "{}/media".format(
            account.business_account_id,
        )

        data = {
            "media_type": "CAROUSEL",
            "children": ",".join(elements),
            "caption": ig_text,
            "locale": "en_us",
        }

        container_response = service.facebook.request(url, **data)
        container_creation_id = container_response["id"]

        # Wait for carousel container to be ready
        cls.wait_for_media_ready(service, container_creation_id)

        #publish the post
        url = "{}/media_publish".format(
            account.business_account_id,
        )

        data = {
            "creation_id" : container_creation_id,
            "locale": "en_us",
        }

        response = service.facebook.request(url, **data)

        return response

    @classmethod
    def get_media_url(cls, service, response):

        post_id = response["id"]

        #en este punto el post YA está publicado. Si falla el pedido del permalink no
        #puede propagarse: publish() lo tomaba como que falló todo, no marcaba
        #instagram_publicado, y la corrida siguiente del cron publicaba el animal de
        #nuevo, duplicando el post.
        try:
            permalink = service.facebook.request("{}?fields=permalink".format(post_id))
        except Exception:
            return {"id": post_id, "url": ""}

        return {
            "id": permalink.get("id", post_id),
            "url": permalink.get("permalink", ""),
        }

    @classmethod
    def leer_error_de_graph(cls, e):
        """El JSON de error que manda Graph en el cuerpo de la respuesta, o None.

        Esto corre en el camino de error, así que no puede tirar nada por su cuenta: el
        cuerpo puede venir vacío, no ser JSON, o estar ya leído.
        """

        leer = getattr(e, "read", None)
        if not callable(leer):
            return None

        try:
            #HTTPError es también un archivo, y el cuerpo se lee UNA sola vez: si alguien
            #ya lo leyó, la segunda vez viene vacío
            cuerpo = leer()
        except Exception:
            return None

        if not cuerpo:
            return None

        if isinstance(cuerpo, bytes):
            cuerpo = cuerpo.decode("utf-8", "replace")

        try:
            datos = json.loads(cuerpo)
        except (ValueError, TypeError):
            return None

        if not isinstance(datos, dict):
            return None

        error = datos.get("error")
        if not isinstance(error, dict):
            return None

        return error

    @classmethod
    def show_error(cls, e):

        #pyfb pide con urlopen, así que un 400 de Graph llega como HTTPError: hasattr(e,
        #"info") daba True, pero e.info() devuelve un HTTPMessage y no un dict, fallaba el
        #isinstance y esto terminaba devolviendo la lista de headers HTTP. El motivo real
        #viene en el cuerpo, que no se leía nunca: token vencido, tope diario de posteos y
        #cuenta mal vinculada se veían los tres igual y no había con qué distinguirlos.
        error = cls.leer_error_de_graph(e)

        if error is not None:

            mensaje = error.get("error_user_msg") or error.get("message") or str(e)

            codigo = error.get("code", "")
            if error.get("error_subcode"):
                codigo = "{}/{}".format(codigo, error["error_subcode"])

            return "Error de Instagram {}: {}".format(codigo, mensaje)

        error_str = str(e)
        if "Media ID is not available" in error_str:
            return "Error: Media ID no está disponible. El contenedor de medios puede no haberse creado correctamente o haber expirado."

        return error_str

    @classmethod
    def update_adoptado_comment(cls, account, animal):

        #el mismo corte que publish(): esto comenta en la cuenta real de la organización y
        #la máquina de desarrollo tiene el token de producción, así que correr
        #update_status_in_ig desde local dejaba comentarios de verdad en posts de verdad
        if settings.ENV == "LOCAL":
            return "ENV=LOCAL: no se comenta. Se hubiera comentado que {} ya fue adoptad{}.".format(
                animal.nombre, "o" if animal.sexo == "M" else "a",
            )

        service = FacebookApiService(account=account)

        if not animal.instagram_post_id:
            return

        update_text = "¡Actualización: Ya fue adoptad{}!".format("o" if animal.sexo == "M" else "a")
        enconded_text = urllib.parse.quote(update_text)

        data = {
            "message": update_text,
        }

        url = "{}/comments".format(animal.instagram_post_id)
        data = service.facebook.request(url, **data)

        animal.instagram_comment_id = data["id"]
        animal.save()

        logger.info("Comentario de adoptado en el post de %s: %s", animal.nombre, animal.instagram_media_url)

        return data

    @classmethod
    def get_all_posts(cls, account, limit=None):

        service = FacebookApiService(account=account)

        url = "{}/media?fields=caption,permalink".format(
            account.business_account_id,
        )

        posts = []

        while True:

            data = service.facebook.request(url)

            if not data["data"]:
                break

            next = data["paging"]["cursors"]["after"]

            posts.extend(data["data"])

            url = "{}/media?fields=caption,permalink&after={}".format(
                account.business_account_id,
                next,
            )

            if limit is not None and len(posts) >= limit:
                break

        if limit is not None:
            return posts[:limit]

        return posts

    @classmethod
    def buscar_post_por_id(cls, posts, post_id):

        for post in posts:
            if str(post.get("id")) == str(post_id):
                return post

        return None

    @classmethod
    def buscar_post_por_nombre(cls, posts, animal):
        """El primer post cuyo caption sea el de este animal, del más nuevo al más viejo."""

        nombre = (animal.nombre or "").strip().lower()
        if not nombre:
            return None

        #el caption arranca con "¡<nombre> en Adopción Responsable!" (tools/generartexto.txt),
        #y los signos son lo único que lo hace específico: sin ellos el post de "Bella Luna"
        #también matchea para "Luna". El match suelto queda de fallback para los posts
        #viejos, escritos a mano antes de la plantilla.
        exacto = "¡{} en adopción responsable!".format(nombre)
        suelto = "{} en adopción responsable".format(nombre)

        for clave in (exacto, suelto):
            for post in posts:
                #hay posts sin caption y ahí post.get("caption", "") devolvía None, no ""
                caption = (post.get("caption") or "").lower()
                if clave in caption:
                    return post

        return None

    @classmethod
    def get_post_for(cls, posts, animal):
        """Le completa al animal el post de Instagram que le corresponde.

        Antes buscaba el nombre adentro del caption, recorría los 50 posts sin cortar en el
        primero que matcheaba -o sea que ganaba el último- y asignaba sin mirar si el animal
        ya tenía instagram_post_id. Dos gatas llamadas Luna alcanzan, y Luna, Mía y Simba se
        repiten todo el tiempo: a la que acababa de publicar se le pisaba el post con el de
        la vieja, y cuando se adoptaba update_status_in_ig comentaba "¡Ya fue adoptada!" en el
        post de la otra, que seguía buscando hogar.
        """

        if animal.instagram_post_id:
            #el que ya publicó bien y sólo se quedó sin permalink: no hay nada que adivinar,
            #su post es el que tiene guardado
            post = cls.buscar_post_por_id(posts, animal.instagram_post_id)
            if post is None:
                logger.info(
                    "El post %s de %s no está entre los últimos posts de la cuenta",
                    animal.instagram_post_id, animal.nombre,
                )
                return None
        else:
            post = cls.buscar_post_por_nombre(posts, animal)
            if post is None:
                logger.info("No se encontró el post de %s en la cuenta", animal.nombre)
                return None

            animal.instagram_post_id = post["id"]

        animal.instagram_media_url = post.get("permalink") or ""
        animal.save(update_fields=["instagram_post_id", "instagram_media_url"])

        logger.info("Post %s guardado para %s", post["id"], animal.nombre)

        return post

    @classmethod
    def send_message(cls, account, message):

        #también escribe con la cuenta real de la organización: desde local el mensaje
        #le llegaba de verdad al destinatario
        if settings.ENV == "LOCAL":
            return "ENV=LOCAL: no se manda. Se hubiera mandado:\n{}".format(message)

        url = "/{}/messages".format(
            account.business_account_id,
        )
        service = FacebookApiService(account=account)

        data = {
            "recipient": {"id": "10207259956078476" },
            "message": {"text": message }
        }

        try:
            data = service.facebook.request(url, **data)
        except Exception as e:
            #e.__dict__ de un HTTPError no dice nada útil: show_error lee el motivo de Graph
            logger.warning("No se pudo mandar el mensaje por Instagram: %s", cls.show_error(e))


