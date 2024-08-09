from .models import Treebank, Component
from rest_framework import serializers


class TreebankSerializer(serializers.ModelSerializer):
    is_public = serializers.SerializerMethodField()

    def get_is_public(self, treebank):
        upload = getattr(treebank, 'treebankupload', None)
        return upload.public if upload else True

    class Meta:
        model = Treebank
        fields = ['slug', 'title', 'description', 'url_more_info', 'variants',
                  'groups', 'is_public']


class ComponentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Component
        fields = ['slug', 'title', 'description', 'nr_sentences', 'nr_words',
                  'variant', 'group']


class MetadataSerializer(serializers.ModelSerializer):
    class Meta:
        model = Treebank
        fields = ['metadata']
