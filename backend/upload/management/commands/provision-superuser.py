import os

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import connections, transaction


class Command(BaseCommand):
    help = 'Create a superuser with a verified email for frontend sign-in.'

    def add_arguments(self, parser):
        parser.add_argument('--username', required=True)
        parser.add_argument('--email', required=True)
        parser.add_argument('--noinput', action='store_true')
        parser.add_argument('--database', default='default', choices=list(connections))

    def handle(self, *args, **options):
        email = options['email']
        database = options['database']
        try:
            validate_email(email)
        except ValidationError as error:
            raise CommandError('; '.join(error.messages)) from error
        if options['noinput'] and not os.getenv('DJANGO_SUPERUSER_PASSWORD'):
            raise CommandError('Set DJANGO_SUPERUSER_PASSWORD when using --noinput.')

        users = get_user_model().objects.db_manager(database)
        if users.filter(username=options['username']).exists():
            raise CommandError('A user with this username already exists.')
        if (users.filter(email__iexact=email).exists()
                or EmailAddress.objects.using(database).filter(email__iexact=email).exists()):
            raise CommandError('A user with this email already exists.')

        with transaction.atomic(using=database):
            call_command(
                'createsuperuser', username=options['username'], email=email,
                interactive=not options['noinput'], database=database,
                stdout=self.stdout, stderr=self.stderr,
            )
            user = users.filter(username=options['username']).first()
            if user is None:
                raise CommandError('Superuser creation was skipped. Run the command in an interactive terminal.')
            EmailAddress.objects.using(database).create(
                user=user, email=user.email, primary=True, verified=True,
            )
        self.stdout.write(self.style.SUCCESS('Email verified; this account can sign in through the frontend.'))
