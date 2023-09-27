from django.core.management.base import BaseCommand, CommandError
import instaloader
from pathlib2 import Path
import json
import urllib
import hashlib
from instaloader.instaloadercontext import copy_session
from django.conf import settings


class Command(BaseCommand):

    def handle(self, *args, **options):

        L = instaloader.Instaloader(save_metadata=False, quiet=True, compress_json=False)

        class CustomContext(instaloader.InstaloaderContext):

            def graphql_query(self, query_hash, variables=None, referer=None, rhx_gis=None):
                """
                Do a GraphQL Query.

                :param query_hash: Query identifying hash.
                :param variables: Variables for the Query.
                :param referer: HTTP Referer, or None.
                :param rhx_gis: 'rhx_gis' variable as somewhere returned by Instagram, needed to 'sign' request
                :return: The server's response dictionary.
                """

                with copy_session(self._session, self.request_timeout) as tmpsession:
                    tmpsession.headers.update(self._default_http_header(empty_session_only=True))
                    del tmpsession.headers['Connection']
                    del tmpsession.headers['Content-Length']
                    tmpsession.headers['authority'] = 'www.instagram.com'
                    tmpsession.headers['scheme'] = 'https'
                    tmpsession.headers['accept'] = '*/*'
                    if referer is not None:
                        tmpsession.headers['referer'] = urllib.parse.quote(referer)

                    variables_json = json.dumps(variables, separators=(',', ':'))

                    if rhx_gis:
                        #self.log("rhx_gis {} query_hash {}".format(rhx_gis, query_hash))
                        values = "{}:{}".format(rhx_gis, variables_json)
                        x_instagram_gis = hashlib.md5(values.encode()).hexdigest()
                        tmpsession.headers['x-instagram-gis'] = x_instagram_gis

                    tmpsession.proxies = {
                        'http':  "http://{}:{}@us-il.proxymesh.com:31280".format(settings.PROXY_MESH_USER, settings.PROXY_MESH_PASSWORD),
                        'https': "http://{}:{}@us-il.proxymesh.com:31280".format(settings.PROXY_MESH_USER, settings.PROXY_MESH_PASSWORD),
                    }
                    resp_json = self.get_json('graphql/query', params={'query_hash': query_hash, 'variables': variables_json}, session=tmpsession)

                    resp_json = self.get_json('graphql/query',
                                            params={'query_hash': query_hash,
                                                    'variables': variables_json},
                                            session=tmpsession)
                if 'status' not in resp_json:
                    self.error("GraphQL response did not contain a \"status\" field.")

                return resp_json

        L.context = CustomContext(True, True, None, 3, 300, None, None, False)

        post = instaloader.Post.from_shortcode(L.context, "Cq6AYP9rCob")

        L.download_post(post, target=Path("/tmp/test"))