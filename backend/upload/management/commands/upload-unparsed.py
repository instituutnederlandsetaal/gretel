from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

from upload.models import TreebankUpload
from upload.services import UploadProcessService
from treebanks.models import Treebank
from services.basex import basex
import traceback


class Command(BaseCommand):
    help = 'Add corpus from directory or compressed file containing ' \
           'unparsed files'

    def add_arguments(self, parser):
        parser.add_argument('input_path',   help='compressed file or directory containing input files')
        parser.add_argument('name',         help='name of the treebank')
        parser.add_argument('public',       help='whether the treebank should be public', type=bool, default=False)

    def handle(self, *args, **options):
        path = Path(options['input_path'])
        print(path.absolute())
        if not path.exists():
            raise CommandError('Cannot find input file(s). Please provide a file, archive, or directory containing files.')
            
        treebank = Treebank(slug=slugify(options['name']), title=options['name'])
        treebank.save()
        upload = TreebankUpload(treebank = treebank, input_file = str(path), public=options['public'])
        service = UploadProcessService(upload)
        
        try:
            service.prepare()
            service.process()
            service.cleanup()
        except Exception as e:
            service.cleanup()
            treebank.delete()
            upload.delete()
            self.stdout.write(self.style.ERROR(f'Indexing failed: {e}'))
            self.stdout.write(self.style.ERROR('No treebank was created.'))
            traceback.print_exc()

