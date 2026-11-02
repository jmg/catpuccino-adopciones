"""Failed logins are counted per visitor, across gunicorn workers.

Run with ENV=TEST (catus/config/config.test.json, sqlite):
    ENV=TEST python3 manage.py test catus.test_login_throttle
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from catus.services import throttle

VISITOR = "190.2.3.4"
GOOD = "una-clave-larga-y-rara"


class FakeMemcached:
    """What the throttle uses of pymemcache, over one shared dict: the store stays
    when each call opens its own client, as the workers do with the real one."""

    def __init__(self, store):
        self.store = store

    def add(self, key, value, expire=0, noreply=None):
        return self.store.setdefault(key, value) == value

    def incr(self, key, value, noreply=False):
        self.store[key] = str(int(self.store[key]) + value)
        return int(self.store[key])

    def get(self, key):
        return self.store.get(key)

    def close(self):
        pass


def fake_memcached():
    store = {}
    return mock.patch("catus.services.throttle._memcached", side_effect=lambda: FakeMemcached(store))


class ClientIpTest(SimpleTestCase):

    def ip(self, forwarded=None):
        extra = {"HTTP_X_FORWARDED_FOR": forwarded} if forwarded is not None else {}
        return throttle.client_ip(RequestFactory().get("/", **extra))

    def test_it_is_the_last_entry_the_one_the_proxy_wrote(self):
        self.assertEqual(self.ip(VISITOR), VISITOR)
        self.assertEqual(self.ip("9.9.9.9, " + VISITOR), VISITOR)
        self.assertEqual(self.ip("1.1.1.1, 9.9.9.9,  " + VISITOR), VISITOR)

    def test_x_real_ip_and_the_peer_are_ignored(self):
        request = RequestFactory().get("/", HTTP_X_REAL_IP="9.9.9.9", REMOTE_ADDR="8.8.8.8")
        self.assertIsNone(throttle.client_ip(request))

    def test_an_internal_or_broken_address_is_not_counted(self):
        for value in (None, "", "garbage", "127.0.0.1", "10.0.0.1", "172.18.0.1", VISITOR + ","):
            self.assertIsNone(self.ip(value), value)

    def test_ipv6_goes_by_its_block(self):
        self.assertEqual(self.ip("2800:810:1:2:aaaa::1"), "2800:810:1:2::")
        self.assertEqual(self.ip("2800:810:1:2:bbbb::9"), "2800:810:1:2::")
        self.assertEqual(self.ip("::ffff:" + VISITOR), VISITOR)


# MD5 only to keep the attempts quick: the throttle does not look at the hash.
@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class LoginThrottleTest(TestCase):
    login_url = "/accounts/login/"
    username = "refugio@example.com"

    def setUp(self):
        patcher = fake_memcached()
        patcher.start()
        self.addCleanup(patcher.stop)

        self.user = get_user_model().objects.create_superuser(self.username, password=GOOD)

    def attempt(self, password, forwarded=VISITOR, url=None):
        self.client.logout()
        return self.client.post(url or self.login_url, {
            "username": self.username, "password": password,
        }, HTTP_X_FORWARDED_FOR=forwarded)

    def fail_until_blocked(self, **kwargs):
        for _ in range(throttle.LOGIN_MAX_FAILURES):
            self.assertEqual(self.attempt("mal", **kwargs).status_code, 200)

    def assertLoggedIn(self, response):
        self.assertEqual(response.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)

    def assertBlocked(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Demasiados intentos")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_the_right_password_works_below_the_limit(self):
        for _ in range(throttle.LOGIN_MAX_FAILURES - 1):
            self.attempt("mal")

        self.assertLoggedIn(self.attempt(GOOD))

    def test_after_the_limit_not_even_the_right_password_gets_in(self):
        self.fail_until_blocked()

        self.assertBlocked(self.attempt(GOOD))

    def test_a_forged_header_does_not_buy_a_new_count(self):
        for i in range(throttle.LOGIN_MAX_FAILURES):
            self.attempt("mal", forwarded="9.9.9.{}, {}".format(i, VISITOR))

        self.assertBlocked(self.attempt(GOOD, forwarded="8.8.8.8, " + VISITOR))

    def test_other_visitors_are_not_affected(self):
        self.fail_until_blocked()

        self.assertLoggedIn(self.attempt(GOOD, forwarded="190.9.9.9"))

    def test_a_good_login_does_not_clear_the_count(self):
        for _ in range(throttle.LOGIN_MAX_FAILURES - 1):
            self.attempt("mal")
        self.assertLoggedIn(self.attempt(GOOD))

        self.attempt("mal")

        self.assertBlocked(self.attempt(GOOD))

    def test_the_admin_login_counts_too(self):
        self.fail_until_blocked(url=reverse("admin:login"))

        self.assertBlocked(self.attempt(GOOD, url=reverse("admin:login")))
        self.assertBlocked(self.attempt(GOOD))

    def test_without_memcached_people_still_log_in(self):
        with mock.patch("catus.services.throttle._memcached", side_effect=OSError("refused")):
            self.assertEqual(self.attempt("mal").status_code, 200)
            self.assertLoggedIn(self.attempt(GOOD))


class PasswordPolicyTest(TestCase):
    """Only for new passwords: logging in with an old, weak one still works."""

    def register(self, password):
        return self.client.post("/accounts/register/", {
            "email": "nueva@example.com", "instagram": "nueva",
            "password1": password, "password2": password,
        })

    def test_a_weak_password_does_not_open_an_account(self):
        for weak in ("corta1", "12345678901", "password", "nueva@example.com"):
            response = self.register(weak)

            self.assertEqual(response.status_code, 200, weak)
            self.assertFalse(get_user_model().objects.filter(email="nueva@example.com").exists(), weak)

    def test_the_form_says_why(self):
        self.assertContains(self.register("12345678901"), "entirely numeric")

    def test_a_good_one_does(self):
        response = self.register(GOOD)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(get_user_model().objects.get(email="nueva@example.com").check_password(GOOD))

    @override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
    def test_an_old_weak_password_still_logs_in(self):
        get_user_model().objects.create_superuser("vieja@example.com", password="123")
        with fake_memcached():
            response = self.client.post("/accounts/login/", {"username": "vieja@example.com", "password": "123"},
                                        HTTP_X_FORWARDED_FOR=VISITOR)

        self.assertEqual(response.status_code, 302)
