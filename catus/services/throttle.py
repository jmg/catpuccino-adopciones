"""Counts every gunicorn worker can see: failed logins and, where a form needs it,
submissions.

They live in the memcached the container runs on localhost for the three sites
(deploycloud/supervisord.conf in the catpuccino repo), so no table and no migration.
Django's cache cannot reach it: its memcached backends need python-memcached or
pylibmc, and the environments only have pymemcache. With memcached down everything
counts as 0: a limit that stops limiting beats a login that fails for everybody.
"""
import ipaddress
import logging

from django.contrib.auth.signals import user_login_failed
from django.core.exceptions import ValidationError
from django.dispatch import receiver
from pymemcache import Client
from pymemcache.exceptions import MemcacheError

logger = logging.getLogger(__name__)

KEY_PREFIX = "adopciones"  # the three sites share this memcached

LOGIN_MAX_FAILURES = 10
LOGIN_WINDOW = 15 * 60
LOGIN_BLOCKED = "Demasiados intentos fallidos desde tu conexión. Esperá 15 minutos y probá de nuevo."


def client_ip(request):
    """The visitor's address, or None when there is no address to count by.

    Requests come through the platform's Traefik and then nginx, which hands
    X-Forwarded-For on untouched (deploycloud/nginx.conf), so REMOTE_ADDR is always
    nginx. Traefik appends the peer it saw, which makes the last entry the only one
    a client cannot write: the first ones are whatever it sent, and Traefik only
    fills in X-Real-IP when the request came without one.

    An internal address means something is hiding the real one, and counting it
    would put everybody in one bucket. IPv6 goes by /64: one host gets the block."""
    last = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[-1].strip()
    try:
        ip = ipaddress.ip_address(last)
    except ValueError:
        return None

    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped

    if not ip.is_global:
        return None

    if ip.version == 6:
        return str(ipaddress.ip_network((str(ip), 64), strict=False).network_address)

    return str(ip)


def _memcached():
    # One per call: gunicorn runs threads, and a pymemcache Client is not thread safe.
    return Client(("127.0.0.1", 11211), connect_timeout=0.5, timeout=0.5)


def _key(scope, who):
    return "{}:{}:{}".format(KEY_PREFIX, scope, who)


def hit(scope, who, window):
    """Counts one more and returns how many there are. The window starts with the
    first one and is not extended by the rest: incr keeps the expiry add() set."""
    try:
        client = _memcached()
        try:
            client.add(_key(scope, who), "0", expire=window, noreply=False)
            return client.incr(_key(scope, who), 1, noreply=False) or 0
        finally:
            client.close()
    except (MemcacheError, OSError) as e:
        logger.warning("Throttle without memcached: %s", e)
        return 0


def count(scope, who):
    try:
        client = _memcached()
        try:
            return int(client.get(_key(scope, who)) or 0)
        finally:
            client.close()
    except (MemcacheError, OSError, ValueError) as e:
        logger.warning("Throttle without memcached: %s", e)
        return 0


class LoginThrottleBackend:
    """First in AUTHENTICATION_BACKENDS, so it stands in front of every login (the
    site's and the admin's): an address with too many recent failures does not get
    its password checked at all, right or wrong.

    It raises ValidationError because the login forms show that as their own error.
    PermissionDenied would read as a wrong password to someone typing the right one.
    A good login does not clear the count: with open registration, anyone could clear
    it between guesses by logging in to an account of their own."""

    def authenticate(self, request, **credentials):
        who = client_ip(request) if request is not None else None
        if who and count("login", who) >= LOGIN_MAX_FAILURES:
            raise ValidationError(LOGIN_BLOCKED, code="login_throttled")

        return None


@receiver(user_login_failed)
def count_failed_login(sender, credentials, request=None, **kwargs):
    who = client_ip(request) if request is not None else None
    if who:
        hit("login", who, LOGIN_WINDOW)
