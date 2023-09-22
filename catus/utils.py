import re
from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from django.utils import timezone
import time


def send_html_email(subject, content, from_email, to_email, fail_silently=False, bcc=None, cc=None, file=None, reply_to=None):

    if not isinstance(to_email, list):
        to_email = [to_email]

    if bcc is None:
        bcc = []
    if not isinstance(bcc, list):
        bcc = [bcc]

    if cc is None:
        cc = []
    if not isinstance(bcc, list):
        cc = [bcc]

    if reply_to is None:
        reply_to = to_email
    if not isinstance(reply_to, list):
        reply_to = [reply_to]

    msg = EmailMultiAlternatives(subject=subject, body=content, from_email=from_email, to=to_email, bcc=bcc, cc=cc, reply_to=reply_to)
    msg.attach_alternative(content, "text/html")

    if not isinstance(file, list):
        files = [file]
    else:
        files = file

    for file in files:
        if file:
            msg.attach(file["name"], file["content"], file["content_type"])

    error = None
    EMAIL_TRIES = 3

    for x in range(EMAIL_TRIES):
        try:
            return msg.send(fail_silently=fail_silently)
        except Exception as e:
            time.sleep(x+1)
            error = e

    raise error


def get_context_columns(animals):

    if len(animals) == 1:
        cols = 12
    elif len(animals) == 2:
        cols = 6
    else:
        cols = 4

    return cols


def clean_html(raw_html):

    CLEANR = re.compile('<.*?>')
    cleantext = re.sub(CLEANR, '', raw_html)
    return cleantext


def rreplace(s, old, new, occurrence):
    li = s.rsplit(old, occurrence)
    return new.join(li)
