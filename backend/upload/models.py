
from django.db import models
from django.contrib.auth.models import User
from pathlib import Path
from treebanks.models import Treebank

import logging

logger = logging.getLogger(__name__)

class UploadError(RuntimeError):
    pass

class TreebankExistsError(RuntimeError):
    pass

class InputFormat(models.TextChoices):
    ALPINO = 'A', 'Alpino'
    CHAT = 'C', 'CHAT'
    TXT = 'T', 'plain text'
    FOLIA = 'F', 'FoLiA'
    AUTO = '', 'auto-detect'

class TreebankUpload(models.Model):
    '''Class to upload texts of various input formats to GrETEL. The model
    can keep information about the upload progress during the various stages
    of the process (i.e. after uploading and inspecting the files, during
    processing and after processing), allowing user interaction in between,
    but if the process can be executed in one run (e.g. after calling a
    Django management command) it does not have to be saved at all. To use,
    make sure that input_file or input_dir is set and subsequently call
    prepare() and process().
    '''
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['treebank'],name='treebankupload_uniqueness')
        ]

    treebank = models.OneToOneField(Treebank, on_delete=models.CASCADE, blank=False, null=False, to_field='slug', primary_key=True)
    '''The treebank for this upload. Is created and destroyed together with the upload.'''

    # Either of these should be set, but not both.
    input_file = models.FileField(upload_to='uploaded_treebanks/', blank=False, null=False) 
    '''File or directory to import from.'''

    input_format = models.CharField(max_length=2, choices=InputFormat.choices[0:])
    '''We validate this and set it if auto-detect is chosen'''

    public = models.BooleanField(default=False)
    '''Whether the treebank should be publicly available.'''

    uploaded_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    '''User who uploaded the treebank.'''
    upload_timestamp = models.DateTimeField(verbose_name='Upload date and time', null=False, blank=True,auto_now=True)
    '''When the upload was started.'''
    processed = models.DateTimeField(null=True, blank=True, editable=False)
    '''When the processing was finished and the treebank is ready to be used.'''

    def cleanup(self):
        '''Remove the uploaded file if it's a django upload.'''
        logger.info(f'Cleaning up {self.input_file}')
        self.input_file.delete()

