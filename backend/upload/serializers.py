# serializers.py
from rest_framework import serializers
from .models import TreebankUpload
from treebanks.models import Treebank

class TreebankUploadSerializer(serializers.ModelSerializer):
    uploaded_by = serializers.ReadOnlyField(source='uploaded_by_id')
    # The upload refers to the treebank by its slug
    # We store the relation as 'treebank' in the database
    slug = serializers.SlugRelatedField(source='treebank', slug_field='slug', queryset=Treebank.objects.all())

    class Meta: 
        model = TreebankUpload
        fields = [
            'slug',
            'input_file', 
            'input_format',
            'uploaded_by',
            'public'
        ]
        read_only_fields = ['uploaded_by']

    def create(self, validated_data):
        validated_data['uploaded_by'] = self.context['request'].user
        return super().create(validated_data)
