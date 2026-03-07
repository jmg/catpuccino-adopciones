from ..models import FacebookAccount
from pyfb.pyfb import Pyfb
from django.conf import settings
import requests
import urllib
import time


class FacebookApiService:

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

    @classmethod
    def wait_for_media_ready(cls, service, creation_id, max_attempts=30, wait_seconds=2):
        """
        Wait for a media container to be ready for publishing.
        Checks the status_code field and waits until it's FINISHED.
        """
        url = "{}?fields=status_code".format(creation_id)

        for attempt in range(max_attempts):
            try:
                response = service.facebook.request(url)
                status_code = response.get("status_code")

                if status_code == "FINISHED":
                    return True
                elif status_code == "ERROR":
                    error_msg = response.get("status", response.get("error_message", "Unknown error"))
                    raise Exception("Media creation failed with status ERROR: {}".format(error_msg))
                # If status is IN_PROGRESS or None (still processing), continue waiting

                if attempt < max_attempts - 1:
                    time.sleep(wait_seconds)
                else:
                    # Last attempt - if status_code is None, it might still work, so don't fail yet
                    if status_code is None:
                        # Give it one more short wait and proceed
                        time.sleep(1)
                        return True
                    raise Exception("Media container status is '{}' after {} attempts. Creation ID: {}".format(status_code, max_attempts, creation_id))

            except Exception as e:
                # If the request itself fails (e.g., media not found), check if it's a critical error
                error_str = str(e)
                if "Media ID is not available" in error_str or "does not exist" in error_str.lower():
                    raise Exception("Media container {} is not available: {}".format(creation_id, error_str))

                # For other errors, if it's the last attempt, raise it
                if attempt == max_attempts - 1:
                    raise Exception("Error checking media status after {} attempts: {}".format(max_attempts, str(e)))

                # Otherwise, wait and retry
                time.sleep(wait_seconds)

        # Should not reach here, but just in case
        raise Exception("Media container not ready after {} attempts. Creation ID: {}".format(max_attempts, creation_id))

    @classmethod
    def publish(cls, animal, ig_text):

        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(ig_text)
            ig_text = soup.text
        except:
            pass

        account = FacebookAccount.objects.all().first()
        service = FacebookApiService(account=account)

        #create elements of post
        images = animal.get_images()

        try:
            if len(images) > 1:
                response_data = cls.publish_multiple_images(service, account, images, ig_text)
            else:
                response_data = cls.publish_one_image(service, account, images, ig_text)

        except Exception as e:
            return cls.show_error(e)

        animal.instagram_publicado = True
        animal.instagram_post_id = response_data["id"]
        animal.instagram_media_url = response_data["url"]

        animal.save()

        return "Publicado!"

    @classmethod
    def publish_one_image(cls, service, account, images, ig_text):

        image = images[0]

        if settings.ENV == "LOCAL":
            image_url = "https://www.feliscatus.com.ar/gallery/5e3802ef-e764-4875-9f36-401c43dd5bad.jpeg"
        else:
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

        return cls.get_media_url(service, response)

    @classmethod
    def publish_multiple_images(cls, service, account, images, ig_text):

        elements = []

        for image in images[0:10]:

            image_url = "{}{}".format(settings.SSL_HOST, image.image_for_instagram.url)

            url = "{}/media".format(
                account.business_account_id,
            )

            data = {
                "image_url": image_url,
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

        return cls.get_media_url(service, response)

    @classmethod
    def get_media_url(cls, service, response):

        url = "{}?fields=permalink".format(response["id"])
        response = service.facebook.request(url)

        return {
            "id": response["id"],
            "url": response["permalink"],
        }

    @classmethod
    def show_error(cls, e):

        if hasattr(e, "info"):
            error_info = e.info()
            if isinstance(error_info, dict):
                # Try to extract meaningful error message
                error_message = error_info.get("error", {}).get("message", str(e))
                error_code = error_info.get("error", {}).get("code", "")
                return "Error {}: {}".format(error_code, error_message)
            return e.info().items()

        # Try to extract error message from exception
        error_str = str(e)
        if "Media ID is not available" in error_str:
            return "Error: Media ID no está disponible. El contenedor de medios puede no haberse creado correctamente o haber expirado."

        return error_str

    @classmethod
    def update_adoptado_comment(cls, account, animal):

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

        print ("Comment posted on {}".format(animal.instagram_media_url))

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
    def get_post_for(cls, posts, animal):

        key_text = "{} en adopción responsable".format(animal.nombre).lower()
        print ("checking for: {}".format(key_text))

        for post in posts:

            caption = post.get("caption", "").lower()

            #print ("checking for: {} in: {}".format(key_text, caption))

            if key_text in caption:

                animal.instagram_post_id = post["id"]
                animal.instagram_media_url = post["permalink"]

                print ("Updating post id: {} for animal: {}".format(post["id"], animal.nombre))
                animal.save()

    @classmethod
    def send_message(cls, account, message):

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
            print (e.__dict__)


