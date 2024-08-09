import logging
import lxml.etree as ET
import patoolib
import tempfile
import traceback

from lxml import etree
from pathlib import Path

from django.utils.text import slugify
from django.utils import timezone

from corpus2alpino.converter import Converter
from corpus2alpino.collectors.filesystem import FilesystemCollector
from corpus2alpino.targets.memory import MemoryTarget
from corpus2alpino.writers.lassy import LassyWriter
from corpus2alpino.readers.auto import AutoReader

from services.alpino import alpino, AlpinoError
from services.basex import basex
from treebanks.models import Component, BaseXDB
from .models import TreebankUpload, UploadError, InputFormat

from typing import Union, Callable, Optional, NoReturn


logger = logging.getLogger(__name__)
MAXIMUM_DATABASE_SIZE = 1024 * 1024 * 10  # 10 MiB
MAX_METADATA_OPTIONS = 100

class UploadProgress:
    def __init__(self):
        self.total_files = 0
        self.processed_files = 0
        self.total_components = 0
        self.processed_components = 0
        self.words = 0
        self.sentences = 0
        self.done = False
        self.error: Union[str, None] = None
        self.message = 'Not started yet'

class UploadProcessService: 
    def __init__(self, upload: TreebankUpload, progress_reporter: Union[Callable[[str, dict], None], None] = None, delete_input_files: bool = False):
        self.upload = upload
        '''The TreebankUpload instance to process.'''
        self.progress_reporter: Optional[Callable[[str, dict], None]] = progress_reporter
        '''A callback function to report progress to the caller.'''

        self.PROGRESS = UploadProgress()

        self._metadata: dict[str, dict] = {}
        '''Metadata discovered during processing. Format is the same as in the Treebank model.'''
        self.components: dict[str, list[Path]] = {}
        '''Files per component discovered.'''
        self._temp_unpack_directory: Optional[tempfile.TemporaryDirectory] = None
        '''Temp dir for unpacking uploaded archives. 
        Need to keep a handle to the temporary directory alive or it will be deleted.'''

        self._input_path: Optional[Path] = None
        '''Path to the directory contained uploaded/unpacked files, or the input_file.
        Only valid after prepare() has been called.'''

        self.delete_input_files: bool = delete_input_files
        '''If the input files should be deleted after processing or errors.'''

    def get_metadata(self):
        '''Return a dict containing the discovered metadata of this treebank,
        available after processing has finished. Format is the same as in the
        Treebank model.'''
        # This method uses the private _metadata attribute but does some
        # optimization by probing metadata facets (e.g. slider if all
        # values of the field are numeric, otherwise checkbox) and removing
        # metadata fields with too many different values.
        
        datas = []
        for fieldname in self._metadata:
            field = self._metadata[fieldname]
            data = {'field': fieldname, 'type': field['type']}
            if field.get('allnumeric', None):
                if field['type'] != 'int':
                    logger.info(f'Changing metadata field {fieldname} from type {field["type"]} to int')
                    data['type'] = 'int'
                data['min_value'] = field['min_value']
                data['max_value'] = field['max_value']
                data['facet'] = 'slider'
            if 'facet' not in data:
                data['facet'] = 'checkbox'
            if len(field['values']) > MAX_METADATA_OPTIONS and data['facet'] == 'checkbox':
                # Do not include checkboxes that consist of too many values
                continue
            datas.append(data)
        return datas

    def _discover_metadata(self, sentence: ET._Element):
        '''Helper method to discover the metadata for a number of sentences.
        This method updates the private _metadata class attribute.
        Sentence should be the <alpino_ds> element'''
        metadata = sentence.find('metadata')
        if metadata is None:
            return
        for meta in metadata.findall('meta'):
            name = meta.get('name')
            type_ = meta.get('type')
            value = meta.get('value')
            m = self._metadata.get(name, None)
            if m:
                if len(m['values']) < MAX_METADATA_OPTIONS:
                    # Only add to values set if not too large -
                    # we only use this to test if a filter should be
                    # created
                    m['values'].add(value)
                if m.get('allnumeric', None):
                    if value.isnumeric():
                        m['min_value'] = min(m['min_value'], int(value))
                        m['max_value'] = max(m['max_value'], int(value))
                    else:
                        m['allnumeric'] = False
            else:
                m = {}
                m['type'] = type_
                m['values'] = {value}
                if value.isnumeric():
                    m['allnumeric'] = True
                    m['min_value'] = int(value)
                    m['max_value'] = int(value)
                self._metadata[name] = m

    
    def _probe_file(self, path: Path):
        '''Probe file format to allow autodiscovery'''
        filename = str(path)
        if filename.lower().endswith('.txt'):
            return InputFormat.TXT
        elif filename.lower().endswith('.cha'):
            return InputFormat.CHAT
        elif filename.lower().endswith('.xml'):
            with open(filename, 'r') as f:
                firstline = f.readline()
                secondline = f.readline()
                if ('<FoLiA' in firstline) or ('<FoLiA' in secondline):
                    return InputFormat.FOLIA
                elif ('<alpino_ds' in firstline) or ('<alpino_ds' in secondline):
                    return InputFormat.ALPINO
        return None

    def _prepare_files(self):
        '''Check whether we need to use input_dir or input_file.
        Unpack the file if it is an archive.
        Finally set the _input_path attribute to the location of the file(s).
        '''
        file = self.upload.input_file
        input_file_path: Path
            
        if isinstance(file, Path): # called from script.
            input_file_path = file
        elif file and getattr(file, '_committed', False): # already saved, or an absolute path supplied by the CLI
            input_file_path = Path(file.name)
            if not input_file_path.is_absolute():
                input_file_path = Path(file.path)
        elif file and hasattr(file.file, 'temporary_file_path'): # still in temp storage
            input_file_path = Path(file.file.temporary_file_path())
        else:
            self._report_error('No input file, archive or directory to read.')
        
        if not input_file_path.exists():
            self._report_error('Input file does not exist.')

        if input_file_path.is_file() and patoolib.is_archive(input_file_path):
            self._temp_unpack_directory = tempfile.TemporaryDirectory()
            self._input_path = Path(self._temp_unpack_directory.name)
            try:
                self._report_progress('Unpacking')
                # Extract the archive to the temporary directory
                patoolib.extract_archive(str(input_file_path.resolve()), outdir=str(self._input_path), interactive=False)
            except: 
                self._report_error('Error unpacking file. Is it a valid archive?')
        else:
            self._input_path = Path(input_file_path) # directory or not an archive, use as-is.
        

    def _add_file(self, path: Path, component: str):
        '''Include the file if it is of a supported format and if no
        files of another supported format had been found. Otherwise
        ignore the file.'''
        format = self._probe_file(path)
        if format is None:
            logger.warning(f'Unrecognized format for file {path}')
            return
        
        if not self.upload.input_format:
            self.upload.input_format = format
        
        if self.upload.input_format != format:
            self._report_error(f'Different input formats found ({format} and {self.upload.input_format}).')
            return

        if component not in self.components:
            self.components[component] = []
            self.PROGRESS.total_components += 1
        self.components[component].append(path)

        self.PROGRESS.total_files += 1
        self._report_progress()

    def _read_input_files(self):
        '''Divide input files into components and probe input format.
        Files in the root of the input_dir will be put in a 'main' component.
        Direct subdirs will become components with the name of the directory.
        All files in the subdirs will be put in the corresponding component.
        '''
        if not self._input_path:
            self._report_error('No input file or directory to read. Did you call prepare()?')
        
        self._report_progress('Reading input files')

        if (self._input_path.is_file()):
            self._add_file(self._input_path, 'main')
            return
        
        # Put all toplevel files in a 'main' component and all files
        # in a subdirectory in a component with the name of the directory
        for entry in self._input_path.glob('*'):
            if entry.is_file():
                self._add_file(entry, 'main')
            if entry.is_dir():
                files = list(entry.glob('**/*'))
                for f in files:
                    if f.is_file():
                        self._add_file(f, entry.name)

    def prepare(self):
        '''Unpack (if input file is zipped) and inspect files. If this
        method runs without error, the processing is ready to start and
        the components class attribute (a dict of all components with
        the corresponding filenames) is available.'''
        try: 
            self._prepare_files()
            self._read_input_files()
            if not self.components:
                self._report_error('No supported input files found.')
        except UploadError:
            raise
        except Exception as e:
            self._report_error(f'Could not prepare upload: {e}')

    def _generate_blocks(self, filenames, componentslug):
        '''A generator function converting all files in filenames to
        Alpino, yielding multiple strings ready to be added to BaseX,
        respecting MAXIMUM_DATABASE_SIZE.'''
        # This method directly manipulates the XML using regular expressions,
        # but it may be a good idea to use lxml for this because of
        # possible changes in what Alpino returns.
        current_output = []
        current_length = 0
        current_file = 0
        nr_words = 0
        nr_sentences = 0
        for filename in filenames:
            if (self.upload.input_format != InputFormat.ALPINO):
                converter = Converter(
                    collector = FilesystemCollector([filename]),
                    annotators = [alpino.annotator],
                    reader = AutoReader(),
                    target = MemoryTarget(),
                    writer = LassyWriter(True))
                # Newer converters yield XML chunks, including a separate closing tag.
                results = [''.join(converter.convert())]
            else:
                # The file is already in alpino format. Mirror the output of the Converter, which is just a list containing a single string with the document.
                with open(filename, 'r') as f:
                    results = [f.read()]
            
            assert len(results) == 1
            current_file += 1
            
            # Add ids to the sentences.
            sentences = self.preprocess_sentences(results[0], current_file, componentslug)
            for sentence, wordcount in sentences:
                current_output.append(sentence)
                current_length += len(sentence)
                nr_words += wordcount
                nr_sentences += 1
                if current_length > MAXIMUM_DATABASE_SIZE:
                    # Yield as soon as the maximum length is reached
                    yield ('<treebank>' + ''.join(current_output) + '</treebank>', nr_words, nr_sentences, current_file)
                    current_length = 0
                    nr_words = 0
                    nr_sentences = 0
                    current_output.clear()
        # Yield once more as soon as all files have been read
        if (current_length > 0):
            yield ('<treebank>' + ''.join(current_output) + '</treebank>',
                nr_words, nr_sentences, current_file)

    def preprocess_sentences(self, alpino_document: str, file_id: int, component_slug: str) -> list[tuple[str, int]]:
        '''Extract all <alpino_ds> sentences, add an id to the sentence. Removes all namespaces.
        Returns the sentences along with the number of words in the sentence.'''
        root = ET.fromstring(alpino_document.encode('utf-8')) # encoding hoop because lxml is stupid
        sentences: list[tuple[str, int]] = []

        # Remove namespaces from the doc.
        for elem in root.getiterator():
            # Skip comments and processing instructions,
            # because they do not have names
            if not (isinstance(elem, etree._Comment) or isinstance(elem, etree._ProcessingInstruction)):
                # Remove a namespace URI in the element's name
                elem.tag = etree.QName(elem).localname
                elem.attrib.pop("xmlns", None)

        # Remove unused namespace declarations
        etree.cleanup_namespaces(root)

        # Use local-name() so that any namespace prefixes are ignored
        for sentence in root.xpath('//alpino_ds'):
            sentence.set('id', f'{component_slug}:${file_id}:{len(sentences)}')
            sentence_root = sentence.xpath('.//node[@cat="top"]/@end')
            # Rarely might encounter a sentence where the root has no start or end attributes.
            # In that case, try counting the words manually.
            wordcount = int(sentence_root[0]) if len(sentence_root) > 0 else int(sentence.xpath('count(.//node[@begin])'))
            sentences.append((ET.tostring(sentence, encoding="unicode"), wordcount))
            self._discover_metadata(sentence)
        
        return sentences
    
    def process(self):
        '''Process prepared treebank upload. This method converts the
        prepared input files to Alpino format, uploads them to BaseX,
        probes metadata and creates Treebank/Component/BaseXDB model
        instances.'''
        
        if not self.upload.treebank or not self._input_path:
            self._report_error('prepare() has to be called first')
        
        if self.upload.input_format != InputFormat.ALPINO:
            try:
                alpino.initialize()
            except AlpinoError as e:
                self._report_error('Alpino not available: {}'.format(str(e)))
        if not basex.test_connection():
            self._report_error('BaseX not available')
        if not self._input_path:
            self._report_error('prepare() has to be called first')
            
        try:
            treebank = self.upload.treebank
            self.PROGRESS.total_files = sum([len(x) for x in self.components.values()])
            self.PROGRESS.total_components = len(self.components)

            for component in self.components:
                self.PROGRESS.processed_components += 1
                self._report_progress(f'Processing component {component}')

                componentslug = slugify(component)
                comp_obj = Component(slug=componentslug, title=component, treebank=treebank)
                filenames = [str(x) for x in self.components[component]]
                if not len(filenames):
                    logger.warning('Component {} is empty.'.format(component))
                    continue

                db_sequence = 0
                component_sentences = 0
                component_words = 0
                for result in self._generate_blocks(filenames, componentslug):
                    doc, words, sentences, total_files_processed = result
                    
                    self.PROGRESS.words += words
                    self.PROGRESS.sentences += sentences
                    component_words += words
                    component_sentences += sentences
                    comp_obj.nr_sentences = component_sentences
                    comp_obj.nr_words = component_words
                    comp_obj.save()
                    
                    self.PROGRESS.processed_files = total_files_processed
                    dbname = f'GRETEL5_{self.upload.treebank.slug}_{componentslug}_{db_sequence}'.upper()
                    basexdb_obj = BaseXDB(dbname, component=comp_obj)
                    basex.create(dbname, doc)
                    basexdb_obj.size = basexdb_obj.get_db_size()
                    basexdb_obj.save()
                    db_sequence += 1
                    self._report_progress() # report inbetween as generating blocks can take a while
            
            if not self.PROGRESS.sentences:
                self._report_error('No sentences could be indexed.')

            treebank.metadata = self.get_metadata()
            treebank.save()
            
            self.upload.processed = timezone.now()
            self.upload.save()
            self.PROGRESS.done = True
            self._report_progress('Processing finished')
        except UploadError:
            raise
        except Exception as e:
            self._report_error(f'Could not process treebank: {e}')

    def cleanup(self):
        '''After indexing or failure, clean up temporary files.'''

        logger.info('Cleaning up')

        if not self._temp_unpack_directory is None:
            self._temp_unpack_directory.cleanup()
            self._temp_unpack_directory = None
        if self.delete_input_files:
            self.upload.cleanup()
        self.upload.save()
    
    def _report_progress(self, message: Optional[str] = None):
        p = self.PROGRESS
        if message:
            p.message = message
        # Else keep previous message

        if self.progress_reporter:
            self.progress_reporter('PROGRESS', p.__dict__)
        
        logger.info(f'''{p.message}\n{
        ''}: {p.processed_files}/{p.total_files} files ({round(p.processed_files / max(1, p.total_files) * 100, 1)}%). {
        ''}{p.processed_components}/{p.total_components} components ({round(p.processed_components / max(1, p.total_components) * 100, 1)})%. {
        ''}{p.words:_} words, {p.sentences:_} sentences.''')

    # Cleanup() might not be smart here, because we might want to keep the treebank around for debugging purposes.
    def _report_error(self, message: str, e: Union[Exception, None] = None) -> NoReturn:
        '''
        Generally abort processing.
        1) Set error state. 2) Mark done. 3) Log error & report to progress reporter. 4) Clean files. 5) Raise an UploadError.
        When this is running as a task in celery, not catching the exception will cause celery to overwrite the progress report with a FAILURE event.
        '''
        p = self.PROGRESS
        p.error = message
        p.done = True
        if (e):
            logger.error(message, exc_info=e)
            p.stack = traceback.format_exc()

        logger.error(message)
        self.cleanup()
        e = UploadError(message)
        if self.progress_reporter:
            self.progress_reporter('FAILURE', {
                'exc_type': type(e).__name__, # required for redis to be happy, FAILURE events need these fields
                'exc_message': str(e),
                **p.__dict__
            })
        raise e
