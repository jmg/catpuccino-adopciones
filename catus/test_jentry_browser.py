"""The pages load the Jentry browser SDK, pointed at the backend's project.

{% jentry_browser %} renders the Sentry browser bundle (pinned version and
integrity) and its init with settings.JENTRY_BROWSER_DSN and the backend's
environment and release. Without a DSN (LOCAL, TEST) it renders nothing.
"""
from django.template import Context, Template
from django.template.loader import get_template
from django.test import SimpleTestCase, override_settings

DSN = "https://0123456789abcdef0123456789abcdef@jentry.example/99"

TEMPLATES_WITH_SDK = ("base.html", "404.html", "500.html", "admin/base_site.html", "forms/form_detail.html", "forms/form_sent.html")


def render():
    return Template("{% load jentry %}{% jentry_browser %}").render(Context({}))


class JentryBrowserTagTests(SimpleTestCase):
    @override_settings(JENTRY_BROWSER_DSN=DSN, SENTRY_ENVIRONMENT="production", SENTRY_RELEASE="deploy-1")
    def test_loads_the_sdk_with_the_dsn_environment_and_release(self):
        html = render()
        self.assertIn('src="https://browser.sentry-cdn.com/7.120.0/bundle.min.js"', html)
        self.assertIn('integrity="sha384-', html)
        self.assertIn('dsn: "%s"' % DSN, html)
        self.assertIn('environment: "production"', html)
        # escapejs writes "-" as -: the same string to JavaScript.
        self.assertIn('release: "deploy\\u002D1"', html)

    @override_settings(JENTRY_BROWSER_DSN="")
    def test_renders_nothing_without_a_dsn(self):
        self.assertEqual(render().strip(), "")

    def test_the_pages_load_it(self):
        for name in TEMPLATES_WITH_SDK:
            source = get_template(name).template.source
            self.assertIn("{% jentry_browser %}", source, name)

    def test_no_sentry_io_dsn_is_left(self):
        for name in TEMPLATES_WITH_SDK:
            self.assertNotIn("sentry.io", get_template(name).template.source, name)

    @override_settings(JENTRY_BROWSER_DSN=DSN, SENTRY_ENVIRONMENT="production", SENTRY_RELEASE="")
    def test_the_admin_pages_carry_it(self):
        html = get_template("admin/base_site.html").render({"title": "x"})
        self.assertIn('dsn: "%s"' % DSN, html)
        self.assertIn("Django", html)
