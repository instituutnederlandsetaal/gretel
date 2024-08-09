from django.urls import include, path
from .views import (
    upload_view,
    upload_status,
)

urlpatterns = [
    path('create/<slug:treebank>/', upload_view, name="upload"),
	path('status/<slug:upload_id>/', upload_status, name="status"),
]
