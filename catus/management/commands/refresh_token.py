from django.core.management.base import BaseCommand, CommandError
from catus.models import *
from catus.services.facebook import FacebookApiService
from datetime import datetime, timedelta, tzinfo

import requests
import logging
logger = logging.getLogger("sentry")


class Command(BaseCommand):

    def handle(self, *args, **options):

        EXPIRE_DELTA = 15

        account = FacebookAccount.objects.all().first()

        if account.facebook_token_expire_at:
            should_update_token = account.facebook_token_expire_at.replace(tzinfo=None) < datetime.now() + timedelta(days=EXPIRE_DELTA)
        else:
            should_update_token = True

        print (account.full_name, "expire at", account.facebook_token_expire_at)

        if should_update_token:

            new_token, expire_in = FacebookApiService.get_long_lived_token(account.facebook_token)

            account.facebook_token = new_token
            account.facebook_token_expire_at = datetime.now() + timedelta(seconds=expire_in)

            print ("updating token", new_token)
            print ("new token expires at", datetime.now() + timedelta(seconds=expire_in))
            print ("*"*80)
            account.save()


