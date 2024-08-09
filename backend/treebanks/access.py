from django.db.models import Q

from .models import Treebank


def available_treebanks(user):
    """Public provisioned corpora and completed uploads accessible to this user."""
    uploads = Q(treebankupload__public=True)
    if user.is_authenticated:
        if user.is_superuser:
            uploads = Q()
        else:
            uploads |= Q(treebankupload__uploaded_by=user)
    return Treebank.objects.filter(
        Q(treebankupload__isnull=True)
        | (Q(treebankupload__processed__isnull=False) & uploads)
    ).select_related('treebankupload')
