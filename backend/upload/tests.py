import json
import os
import tempfile
from io import StringIO
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from allauth.account.models import EmailAddress
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from django.middleware.csrf import _get_new_csrf_string
from rest_framework.test import APIClient

from search.models import SearchQuery
from treebanks.models import Treebank, Component, BaseXDB
from .models import TreebankUpload, InputFormat, UploadError
from .services import UploadProcessService
from .tasks import process_upload


ALPINO_XML = b'''<alpino_ds>
<node cat="top" begin="0" end="2"><node word="Hello" begin="0" end="1"/><node word="world" begin="1" end="2"/></node>
<sentence>Hello world</sentence>
</alpino_ds>'''


class UploadTestCase(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.enterContext(self.settings(MEDIA_ROOT=self.directory, CACHING_DIR=self.directory))

    def make_upload(self, slug='test-upload', filename='input.xml', content=ALPINO_XML, **kwargs):
        treebank = Treebank.objects.create(slug=slug, title=slug)
        return TreebankUpload.objects.create(
            treebank=treebank, input_file=SimpleUploadedFile(filename, content),
            input_format=kwargs.pop('input_format', ''), public=kwargs.pop('public', True), **kwargs,
        )


class UploadProcessingTests(UploadTestCase):
    def mock_services(self):
        self.enterContext(patch('upload.services.basex.test_connection', return_value=True))
        create = self.enterContext(patch('upload.services.basex.create'))
        self.enterContext(patch.object(BaseXDB, 'get_db_size', return_value=1))
        return create

    def test_explicit_formats_match_detected_formats(self):
        cases = [(InputFormat.ALPINO, 'xml', ALPINO_XML), (InputFormat.TXT, 'txt', b'Hello'),
                 (InputFormat.CHAT, 'cha', b'Hello'), (InputFormat.FOLIA, 'xml', b'<FoLiA/>')]
        for index, (format_, extension, content) in enumerate(cases):
            with self.subTest(format=format_):
                upload = self.make_upload(slug=f'format-{index}', filename=f'input.{extension}',
                                          content=content, input_format=str(format_))
                upload.refresh_from_db()
                service = UploadProcessService(upload)
                service.prepare()
                self.assertEqual(service.PROGRESS.total_files, 1)
                self.assertEqual(service._input_path, Path(upload.input_file.path))

    def test_alpino_without_metadata_does_not_require_parser(self):
        create = self.mock_services()
        initialize = self.enterContext(patch('upload.services.alpino.initialize', side_effect=RuntimeError('no parser')))
        upload = self.make_upload(input_format='A')
        service = UploadProcessService(upload)
        service.prepare()
        service.process()
        upload.refresh_from_db()
        self.assertIsNotNone(upload.processed)
        self.assertEqual(upload.treebank.metadata, [])
        self.assertEqual(upload.treebank.components.get().nr_sentences, 1)
        create.assert_called_once()
        initialize.assert_not_called()

    def test_real_plaintext_converter_chunks_are_combined(self):
        create = self.mock_services()
        self.enterContext(patch('upload.services.alpino.initialize'))

        class Annotator:
            def annotate(self, document):
                for utterance in document.utterances:
                    utterance.annotations['alpino'] = ALPINO_XML.decode()

        self.enterContext(patch('upload.services.alpino.annotator', Annotator(), create=True))
        upload = self.make_upload(filename='input.txt', content=b'Hello world.\n')
        service = UploadProcessService(upload)
        service.prepare()
        service.process()
        self.assertEqual(upload.treebank.components.get().nr_sentences, 1)
        self.assertEqual(upload.treebank.components.get().nr_words, 2)
        create.assert_called_once()

    def test_legacy_converter_complete_document_is_supported(self):
        self.mock_services()
        self.enterContext(patch('upload.services.alpino.initialize'))
        self.enterContext(patch('upload.services.alpino.annotator', object(), create=True))
        converter = self.enterContext(patch('upload.services.Converter'))
        converter.return_value.convert.return_value = iter(['<treebank>' + ALPINO_XML.decode() + '</treebank>'])
        upload = self.make_upload(filename='input.txt', content=b'Hello world.')
        service = UploadProcessService(upload)
        service.prepare()
        service.process()
        self.assertEqual(upload.treebank.components.get().nr_sentences, 1)

    def test_conversion_error_fails_upload(self):
        self.mock_services()
        self.enterContext(patch('upload.services.alpino.initialize'))
        self.enterContext(patch('upload.services.alpino.annotator', object(), create=True))
        self.enterContext(patch('upload.services.Converter', side_effect=ValueError('invalid input')))
        upload = self.make_upload(filename='input.txt', content=b'Hello world.')
        service = UploadProcessService(upload)
        service.prepare()
        with self.assertRaisesMessage(UploadError, 'invalid input'):
            service.process()
        upload.refresh_from_db()
        self.assertIsNone(upload.processed)

    def test_unsupported_input_is_rejected(self):
        service = UploadProcessService(self.make_upload(filename='input.csv', content=b'Hello'))
        with self.assertRaisesMessage(UploadError, 'No supported input files'):
            service.prepare()

    def test_no_indexed_sentences_is_failure(self):
        self.mock_services()
        upload = self.make_upload(input_format='A')
        service = UploadProcessService(upload)
        service.prepare()
        with patch.object(service, '_generate_blocks', return_value=iter([])):
            with self.assertRaisesMessage(UploadError, 'No sentences could be indexed'):
                service.process()
        upload.refresh_from_db()
        self.assertIsNone(upload.processed)

    def test_task_failure_removes_treebank_even_if_cleanup_fails(self):
        upload = self.make_upload()
        with patch('upload.tasks.UploadProcessService') as service, patch.object(process_upload, 'update_state'):
            service.return_value.prepare.side_effect = UploadError('original failure')
            service.return_value.cleanup.side_effect = OSError('cleanup failed')
            with self.assertRaisesMessage(UploadError, 'original failure'):
                process_upload.run(upload.pk)
        self.assertFalse(Treebank.objects.filter(pk=upload.pk).exists())

    def test_task_success_returns_progress_and_removes_input(self):
        self.mock_services()
        upload = self.make_upload(input_format='A')
        path = Path(upload.input_file.path)
        with patch.object(process_upload, 'update_state'):
            progress = process_upload.run(upload.pk)
        self.assertTrue(progress['done'])
        self.assertEqual(progress['sentences'], 1)
        self.assertFalse(path.exists())


class UploadEndpointTests(UploadTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.create_user(username='owner', password='test-password')
        self.client.force_login(self.user, backend='django.contrib.auth.backends.ModelBackend')
        self.delay = self.enterContext(patch('upload.views.process_upload.delay',
                                           return_value=SimpleNamespace(id='11111111-1111-1111-1111-111111111111')))

    def submit(self, public=True, slug='api-upload', **overrides):
        data = {'title': slug, 'input_file': SimpleUploadedFile('input.xml', ALPINO_XML),
                'input_format': 'A', 'public': str(public).lower()}
        data.update(overrides)
        return self.client.post(f'/upload/create/{slug}/', data, format='multipart')

    def test_anonymous_uploads_are_rejected_before_creating_rows_or_queueing(self):
        self.client.logout()
        for public in (True, False):
            with self.subTest(public=public):
                self.assertEqual(self.submit(public=public).status_code, 403)
        self.assertFalse(Treebank.objects.exists())
        self.assertFalse(TreebankUpload.objects.exists())
        self.assertFalse(any(path.is_file() for path in self.directory.rglob('*')))
        self.delay.assert_not_called()

    def test_registered_user_can_upload_public_dataset(self):
        self.assertEqual(self.submit().status_code, 201)
        upload = TreebankUpload.objects.get(pk='api-upload')
        self.assertEqual(upload.uploaded_by, self.user)
        self.assertTrue(upload.public)

    def test_anonymous_status_polling_is_rejected_before_contacting_celery(self):
        self.client.logout()
        with patch('upload.views.process_upload.AsyncResult') as result:
            self.assertEqual(self.client.get('/upload/status/task-id/').status_code, 403)
        result.assert_not_called()

    def test_registered_user_can_poll_upload_status(self):
        with patch('upload.views.process_upload.AsyncResult',
                   return_value=SimpleNamespace(status='PENDING')) as result:
            response = self.client.get('/upload/status/task-id/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'PENDING')
        result.assert_called_once_with('task-id')

    @override_settings(REGISTRATION_ENABLED=False)
    def test_provisioned_superuser_can_sign_in_upload_and_publish_with_registration_closed(self):
        password = 'test-provisioned-password'
        with patch.dict(os.environ, {'DJANGO_SUPERUSER_PASSWORD': password}):
            call_command('provision-superuser', username='admin', email='admin@example.org',
                         noinput=True, stdout=StringIO())
        admin = User.objects.get(username='admin')
        self.assertTrue(admin.is_superuser)
        self.assertTrue(admin.is_staff)
        self.assertTrue(EmailAddress.objects.get(user=admin, email=admin.email).verified)

        self.client.logout()
        login = self.client.post('/_allauth/browser/v1/auth/login',
                                 {'email': admin.email, 'password': password}, format='json')
        self.assertEqual(login.status_code, 200)
        self.assertTrue(login.json()['meta']['is_authenticated'])
        self.assertEqual(self.submit().status_code, 201)
        upload = TreebankUpload.objects.get(pk='api-upload')
        self.assertEqual(upload.uploaded_by, admin)
        self.assertTrue(upload.public)

        with patch('upload.services.basex.test_connection', return_value=True), \
                patch('upload.services.basex.create'), \
                patch.object(BaseXDB, 'get_db_size', return_value=1), \
                patch.object(process_upload, 'update_state'):
            process_upload.run(upload.pk)
        public_client = APIClient()
        listing = public_client.get('/treebanks/treebank/').data
        self.assertEqual([bank['slug'] for bank in listing], ['api-upload'])
        self.assertTrue(listing[0]['is_public'])

    def test_session_upload_saves_owner(self):
        self.client.force_login(self.user, backend='django.contrib.auth.backends.ModelBackend')
        self.assertEqual(self.submit(public=False).status_code, 201)
        self.assertEqual(TreebankUpload.objects.get(pk='api-upload').uploaded_by, self.user)

    def test_session_upload_requires_csrf_token(self):
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.force_login(self.user, backend='django.contrib.auth.backends.ModelBackend')
        self.assertEqual(self.submit(public=False).status_code, 403)
        self.delay.assert_not_called()
        token = _get_new_csrf_string()
        self.client.cookies['csrftoken'] = token
        self.client.credentials(HTTP_X_CSRFTOKEN=token)
        self.assertEqual(self.submit(public=False).status_code, 201)
        self.assertEqual(TreebankUpload.objects.get(pk='api-upload').uploaded_by, self.user)

    def test_invalid_upload_rolls_back_treebank(self):
        self.assertEqual(self.submit(input_format='invalid').status_code, 400)
        self.assertFalse(Treebank.objects.filter(pk='api-upload').exists())
        self.delay.assert_not_called()

    def test_queue_failure_removes_rows_and_input(self):
        self.delay.side_effect = RuntimeError('broker unavailable')
        self.assertEqual(self.submit().status_code, 503)
        self.assertFalse(Treebank.objects.filter(pk='api-upload').exists())
        self.assertFalse(TreebankUpload.objects.filter(pk='api-upload').exists())
        self.assertFalse(any(path.is_file() for path in self.directory.rglob('*')))

    def test_existing_treebank_cannot_be_replaced(self):
        Treebank.objects.create(slug='api-upload', title='Original', groups=[{'slug': 'A'}])
        self.assertEqual(self.submit().status_code, 400)
        self.assertEqual(Treebank.objects.get(pk='api-upload').title, 'Original')
        self.delay.assert_not_called()


class TreebankAccessTests(UploadTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.owner = User.objects.create_user(username='owner', password='test-password')
        self.other = User.objects.create_user(username='other')
        self.private = self.make_upload(slug='private', public=False, uploaded_by=self.owner, processed=timezone.now())
        self.public = self.make_upload(slug='public', processed=timezone.now())
        self.pending = self.make_upload(slug='pending', uploaded_by=self.owner)
        self.provisioned = Treebank.objects.create(slug='provisioned', title='Provisioned')
        for bank in [self.private.treebank, self.public.treebank, self.pending.treebank, self.provisioned]:
            component = Component.objects.create(treebank=bank, slug='main', title='Main', nr_words=2, nr_sentences=1)
            BaseXDB.objects.create(dbname=bank.pk.upper(), component=component, size=1)

    def listing(self):
        return {bank['slug']: bank for bank in self.client.get('/treebanks/treebank/').data}

    def test_anonymous_listing_contains_ready_public_and_provisioned(self):
        self.assertEqual(set(self.listing()), {'public', 'provisioned'})

    def test_owner_can_see_private_upload_with_correct_public_flag(self):
        self.client.force_login(self.owner, backend='django.contrib.auth.backends.ModelBackend')
        listing = self.listing()
        self.assertEqual(set(listing), {'private', 'public', 'provisioned'})
        self.assertFalse(listing['private']['is_public'])
        self.assertTrue(listing['provisioned']['is_public'])

    def test_other_user_cannot_see_private_upload(self):
        self.client.force_authenticate(self.other)
        self.assertNotIn('private', self.listing())

    def test_superuser_sees_ready_private_uploads_but_not_pending(self):
        self.other.is_superuser = True
        self.other.save()
        self.client.force_authenticate(self.other)
        self.assertEqual(set(self.listing()), {'private', 'public', 'provisioned'})

    def test_private_and_pending_detail_endpoints_are_hidden(self):
        for slug in ['private', 'pending']:
            for endpoint in ['components', 'metadata']:
                with self.subTest(slug=slug, endpoint=endpoint):
                    self.assertEqual(self.client.get(f'/treebanks/treebank/{slug}/{endpoint}/').status_code, 404)

    def test_direct_private_and_pending_searches_are_hidden(self):
        with patch('search.views.basex.perform_query') as basex:
            for slug in ['private', 'pending']:
                for endpoint in ['search', 'metadata-count']:
                    with self.subTest(slug=slug, endpoint=endpoint):
                        response = self.client.post(f'/search/{endpoint}/',
                            {'treebank': slug, 'components': ['main'], 'xpath': '//node'}, format='json')
                        self.assertEqual(response.status_code, 404)
                response = self.client.post('/search/tree/', {'database': slug.upper(), 'sentence_id': '1'}, format='json')
                self.assertEqual(response.status_code, 404)
            basex.assert_not_called()

    def test_owner_can_retrieve_private_tree(self):
        self.client.force_authenticate(self.owner)
        with patch('search.views.basex.perform_query', return_value=ALPINO_XML.decode()):
            response = self.client.post('/search/tree/', {'database': 'PRIVATE', 'sentence_id': '1'}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_owner_can_search_private_upload(self):
        self.client.force_authenticate(self.owner)
        with patch('search.views.run_search_query.delay'), patch.object(SearchQuery, 'get_results', return_value=([], 100, {})):
            response = self.client.post('/search/search/',
                {'treebank': 'private', 'components': ['main'], 'xpath': '//node'}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_public_upload_and_provisioned_treebank_are_searchable_anonymously(self):
        with patch('search.views.run_search_query.delay'), patch.object(SearchQuery, 'get_results', return_value=([], 100, {})):
            for slug in ['public', 'provisioned']:
                with self.subTest(slug=slug):
                    response = self.client.post('/search/search/',
                        {'treebank': slug, 'components': ['main'], 'xpath': '//node'}, format='json')
                    self.assertEqual(response.status_code, 200)

    def test_owner_can_count_private_metadata(self):
        self.client.force_authenticate(self.owner)
        bank = self.private.treebank
        bank.metadata = [{'field': 'source', 'type': 'text', 'facet': 'checkbox'}]
        bank.save()
        result = '<metadata><meta name="source" type="text"><count value="uploaded">1</count></meta></metadata>'
        with patch('search.views.basex.perform_query', return_value=result) as basex:
            response = self.client.post('/search/metadata-count/',
                {'treebank': 'private', 'components': ['main'], 'xpath': '//node'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'source': {'uploaded': 1}})
        basex.assert_called_once()

    def test_public_search_cannot_reuse_private_query_id(self):
        query = SearchQuery.objects.create(xpath='//node', variables=[])
        query.components.add(self.private.treebank.components.get())
        response = self.client.post('/search/search/',
            {'treebank': 'public', 'components': ['main'], 'xpath': '//node', 'query_id': query.pk}, format='json')
        self.assertEqual(response.status_code, 404)

    def test_request_cannot_reassign_private_database(self):
        with patch('search.views.basex.perform_query') as basex:
            response = self.client.post('/search/search/',
                {'treebank': 'provisioned', 'components': ['PRIVATE'], 'xpath': '//node'}, format='json')
            self.assertEqual(response.status_code, 400)
            response = self.client.post('/search/metadata-count/',
                {'treebank': 'provisioned', 'components': ['PRIVATE'], 'xpath': '//node'}, format='json')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(BaseXDB.objects.get(pk='PRIVATE').component.treebank_id, 'private')
        basex.assert_not_called()

    def test_request_cannot_discover_unregistered_basex_database(self):
        with patch('search.views.basex.perform_query') as basex:
            response = self.client.post('/search/search/',
                {'treebank': 'provisioned', 'components': ['ORPHAN'], 'xpath': '//node'}, format='json')
            self.assertEqual(response.status_code, 400)
            response = self.client.post('/search/metadata-count/',
                {'treebank': 'provisioned', 'components': ['ORPHAN'], 'xpath': '//node'}, format='json')
            self.assertEqual(response.status_code, 404)
            response = self.client.post('/search/tree/',
                {'database': 'ORPHAN', 'sentence_id': '1'}, format='json')
            self.assertEqual(response.status_code, 404)
        basex.assert_not_called()


class ImportExistingTests(UploadTestCase):
    def test_omitted_json_fields_default_to_lists(self):
        path = self.directory / 'import.json'
        path.write_text(json.dumps({'slug': 'imported', 'title': 'Imported', 'components': []}))
        module = import_module('upload.management.commands.import-existing')
        with patch.object(module.basex, 'test_connection', return_value=True):
            module.Command().handle(configuration=str(path))
        bank = Treebank.objects.get(pk='imported')
        self.assertEqual(bank.groups, [])
        self.assertEqual(bank.variants, [])
        self.assertEqual(bank.metadata, [])


class RegistrationPolicyTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.signup = {'username': 'new-user', 'email': 'new@example.org',
                       'password': 'test-registration-password'}

    @override_settings(REGISTRATION_ENABLED=False)
    def test_registration_is_closed_for_both_headless_clients(self):
        for client in ('browser', 'app'):
            with self.subTest(client=client):
                response = self.client.post(f'/_allauth/{client}/v1/auth/signup', self.signup, format='json')
                self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.exists())

    @override_settings(REGISTRATION_ENABLED=True, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_registration_can_be_enabled(self):
        response = self.client.post('/_allauth/browser/v1/auth/signup', self.signup, format='json')
        self.assertEqual(response.status_code, 401)  # Email verification is still required.
        self.assertTrue(User.objects.filter(username=self.signup['username']).exists())

    def test_allauth_config_matches_registration_setting(self):
        for registration in (True, False):
            with self.subTest(registration=registration), self.settings(REGISTRATION_ENABLED=registration):
                config = self.client.get('/_allauth/browser/v1/config').json()
                self.assertEqual(config['data']['account']['is_open_for_signup'], registration)


class SuperuserProvisioningTests(TestCase):
    def provision(self, **options):
        call_command('provision-superuser', username='admin', email='admin@example.org',
                     noinput=True, stdout=StringIO(), **options)

    def test_noninteractive_provisioning_requires_password_without_creating_account(self):
        with patch.dict(os.environ, {'DJANGO_SUPERUSER_PASSWORD': ''}):
            with self.assertRaisesMessage(CommandError, 'Set DJANGO_SUPERUSER_PASSWORD'):
                self.provision()
        self.assertFalse(User.objects.exists())

    def test_provisioning_does_not_reassign_an_existing_users_email(self):
        existing = User.objects.create_user(username='other', email='ADMIN@example.org')
        with patch.dict(os.environ, {'DJANGO_SUPERUSER_PASSWORD': 'test-password'}):
            with self.assertRaisesMessage(CommandError, 'A user with this email already exists'):
                self.provision()
        existing.refresh_from_db()
        self.assertFalse(existing.is_superuser)
        self.assertEqual(User.objects.count(), 1)
        self.assertFalse(EmailAddress.objects.exists())

    def test_email_setup_failure_rolls_back_account_creation(self):
        with patch.dict(os.environ, {'DJANGO_SUPERUSER_PASSWORD': 'test-password'}), \
                patch('allauth.account.models.EmailAddress.objects.using') as addresses:
            addresses.return_value.filter.return_value.exists.return_value = False
            addresses.return_value.create.side_effect = RuntimeError('email setup failed')
            with self.assertRaisesMessage(RuntimeError, 'email setup failed'):
                self.provision()
        self.assertFalse(User.objects.exists())
