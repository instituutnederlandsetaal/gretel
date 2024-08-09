from celery import shared_task, Task
from .models import TreebankUpload
from .services import UploadProcessService
import logging

logger = logging.getLogger(__name__)

@shared_task(bind=True, name='process_upload')
def process_upload(self: Task, upload_id: str):

	self.update_state(state='PROGRESS', meta={'message': 'starting', 'done': False})
	
	upload = TreebankUpload.objects.get(treebank=upload_id)
	service = UploadProcessService(upload, progress_reporter=lambda state, progress: self.update_state(state=state, meta=progress), delete_input_files=True)

	try:
		service.prepare()
		service.process()
		service.cleanup()
	except Exception:
		try:
			service.cleanup()
		except Exception:
			logger.exception('Could not clean up failed upload')
		finally:
			upload.treebank.delete()
		raise
	return service.PROGRESS.__dict__
