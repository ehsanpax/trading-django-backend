from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TradeJournalViewSet, TradeJournalAttachmentViewSet

router = DefaultRouter()
router.register(r'journals', TradeJournalViewSet, basename='trade-journal')
router.register(r'attachments', TradeJournalAttachmentViewSet, basename='journal-attachment')

urlpatterns = router.urls
