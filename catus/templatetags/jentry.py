"""{% jentry_browser %}: the Jentry (Sentry-compatible) browser SDK for a page.

Put it in the page's <head>, after {% load jentry %}. It loads Sentry's browser
bundle from its CDN, pinned by version and integrity, and reports the page's
uncaught errors and unhandled promise rejections to settings.JENTRY_BROWSER_DSN
(the backend's own project), with the backend's environment and release. With
no DSN (LOCAL, TEST) it renders nothing.
"""
from django import template
from django.conf import settings

register = template.Library()


@register.inclusion_tag("jentry/browser.html")
def jentry_browser():
    return {
        "dsn": getattr(settings, "JENTRY_BROWSER_DSN", ""),
        "environment": getattr(settings, "SENTRY_ENVIRONMENT", "") or "production",
        "release": getattr(settings, "SENTRY_RELEASE", ""),
    }
