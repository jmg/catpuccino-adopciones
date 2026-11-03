# django_conventions

django-conventions 0.2.0 (Juan Manuel Garcia, GPL v3), which builds the URLs
from the views in catus/views. Copied here because 0.2.0 does not run on
Django 4+ (`django.conf.urls.url`) or Python 3.12 (`find_module().load_module()`).
Only those two calls changed (and a dead `Context` in rest/views.py).
