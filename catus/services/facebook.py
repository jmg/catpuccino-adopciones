from ..models import FacebookAccount
from pyfb.pyfb import Pyfb
from django.conf import settings
import requests
import urllib


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

        data = service.facebook.request(url, **data)

        #publish the post
        url = "{}/media_publish".format(
            account.business_account_id,
        )

        data = {
            "creation_id" : data["id"],
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

            data = service.facebook.request(url, **data)

            elements.append(data["id"])

        #create container of elements
        data = {
            "media_type": "CAROUSEL",
            "children": ",".join(elements),
            "caption": ig_text,
            "locale": "en_us",
        }

        data = service.facebook.request(url, **data)

        #publish the post
        url = "{}/media_publish".format(
            account.business_account_id,
        )

        data = {
            "creation_id" : data["id"],
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
            return e.info().items()

        return e

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


