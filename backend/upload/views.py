from rest_framework.response import Response
from rest_framework.decorators import (
    api_view, parser_classes, renderer_classes, authentication_classes, permission_classes
)
from rest_framework.request import Request
from rest_framework.exceptions import ValidationError

from rest_framework.parsers import MultiPartParser
from rest_framework.renderers import JSONRenderer, BrowsableAPIRenderer
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework import status
from django.utils.text import slugify
from django.db import transaction
from rest_framework.permissions import IsAuthenticated
from copy import copy
import logging

from treebanks.serializers import TreebankSerializer
from upload.serializers import TreebankUploadSerializer
from upload.tasks import process_upload

logger = logging.getLogger(__name__)

@api_view(['POST'])
@authentication_classes([SessionAuthentication, BasicAuthentication])
@permission_classes([IsAuthenticated])
@renderer_classes([JSONRenderer, BrowsableAPIRenderer])
@parser_classes([MultiPartParser])
def upload_view(request: Request, treebank: str):
    data = copy(request.data)
    data['slug'] = slugify(treebank)
    treebank_serializer = TreebankSerializer(data=data)
    upload_serializer = TreebankUploadSerializer(data=data, context={'request': request})
    try:
        with transaction.atomic():
            treebank_serializer.is_valid(raise_exception=True)
            treebank_obj = treebank_serializer.save()
            upload_serializer.is_valid(raise_exception=True)
            upload_obj = upload_serializer.save()
    except ValidationError as error:
        return Response(
            {'status': 'FAILURE', 'info': {
                'error': format_serializer_errors(error.detail),
                'message': 'Invalid data', 'done': True,
            }},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Queue after committing so the worker can read the new upload immediately.
    try:
        task = process_upload.delay(upload_id=upload_obj.treebank.slug)
    except Exception:
        logger.exception('Could not queue treebank upload')
        try:
            upload_obj.cleanup()
        except Exception:
            logger.exception('Could not remove input file after queue failure')
        finally:
            treebank_obj.delete()
        return Response(
            {'status': 'FAILURE', 'info': {
                'error': 'Could not queue the upload. Please try again later.',
                'message': 'Upload unavailable', 'done': True,
            }},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    return Response({'upload_id': task.id}, status=status.HTTP_201_CREATED)


def format_serializer_errors(errors: dict[str, dict[str, list[str]]]) -> str:
    def recursive_format(error_dict, parent_key=''):
        messages = []
        for key, value in error_dict.items():
            full_key = f"{parent_key}{key}" if parent_key else key
            if isinstance(value, dict):
                messages.extend(recursive_format(value, f"{full_key}."))
            elif isinstance(value, list):
                for sub_value in value:
                    if isinstance(sub_value, dict):
                        messages.extend(recursive_format(sub_value, f"{full_key}."))
                    else:
                        messages.append(f"{full_key}: {sub_value}")
            else:
                messages.append(f"{full_key}: {value}")
        return messages
    
    formatted_messages = recursive_format(errors)
    return "\n".join(formatted_messages)

@api_view(['GET'])
@authentication_classes([SessionAuthentication, BasicAuthentication])
@permission_classes([IsAuthenticated])
@renderer_classes([JSONRenderer, BrowsableAPIRenderer])
def upload_status(request: Request, upload_id: str):
	result = process_upload.AsyncResult(upload_id)
	
	info = {
		'error': None,
		'message': '',
		'done': False
	}
	if result.status == 'PENDING':
		return Response({'status': result.status, 'info': info}, status=status.HTTP_200_OK)
	elif result.status == 'PROGRESS':
		return Response({'status': result.status, 'info': result.info}, status=status.HTTP_200_OK)
	elif result.status == 'SUCCESS':
		return Response({'status': result.status, 'info': result.info}, status=status.HTTP_200_OK)
	elif result.status == 'FAILURE':
		info['done'] = True
		# Check if we have an exception or a failed progress event.
		if isinstance(result.info, Exception):
			info['error'] = str(result.info)
			info['done'] = True
			info['message'] = 'An error occurred'
		elif isinstance(result.info, dict):
			info = result.info
			# Set some fields the client expects
			info['done'] = True
			info['message'] = info.get('message', 'An error occurred')
			info['error'] = info.get('error', 'Unknown error')
		else:
			info['error'] = 'Unknown error'
			info['message'] = 'An error occurred'
			info['done'] = True

		return Response({'status': result.status, 'info': info}, status=status.HTTP_200_OK)
	else:
		info['error'] = f'Unexpected status: {result.status}'
		info['done'] = True
		info['message'] = 'An error occurred'

		return Response(
			{'status': 'UNEXPECTED', 'info': info},
			status=status.HTTP_500_INTERNAL_SERVER_ERROR
		)
