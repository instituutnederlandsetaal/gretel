from .models import Treebank
from .access import available_treebanks
from .serializers import (
    TreebankSerializer, ComponentSerializer, MetadataSerializer
)
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response


@api_view(['GET'])
def treebank_view(request):
    treebanks = available_treebanks(request.user)
    serializer = TreebankSerializer(treebanks, many=True)
    return Response(serializer.data)


@api_view(['GET'])
def treebank_metadata_view(request, treebank):
    try:
        treebank = available_treebanks(request.user).get(slug=treebank)
    except Treebank.DoesNotExist:
        return Response(None, status=status.HTTP_404_NOT_FOUND)
    serializer = MetadataSerializer(treebank, many=False)
    return Response(serializer.data)


@api_view(['GET'])
def treebank_components_view(request, treebank):
    try:
        treebank = available_treebanks(request.user).get(slug=treebank)
    except Treebank.DoesNotExist:
        return Response(None, status=status.HTTP_404_NOT_FOUND)
    components = treebank.components
    serializer = ComponentSerializer(components, many=True)
    return Response(serializer.data)
