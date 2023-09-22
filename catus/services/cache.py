from django.conf import settings
from pymemcache import Client
import pickle


class CacheService(object):

    def __init__(self):
        self.cache = Client('localhost')

    def set(self, key, value):

        data = pickle.dumps(value)
        self.cache.set(key, data)

    def get(self, key):

        data = self.cache.get(key)
        if data:
            return pickle.loads(data)
