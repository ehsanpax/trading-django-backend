from django.urls import path
from .views import (
    InstrumentListView,
    AnalysisSubmitView,
    AnalysisJobStatusView,
    AnalysisResultView,
    AnalysisJobListView, # Added
    AnalysisTypeListView,
    AnalysisTypeDetailView,
)

urlpatterns = [
    path('instruments/', InstrumentListView.as_view(), name='instrument-list-create'), # Renamed for clarity
    path('submit/', AnalysisSubmitView.as_view(), name='analysis-submit'),
    path('jobs/', AnalysisJobListView.as_view(), name='analysis-job-list'), # New endpoint
    path('jobs/<uuid:job_id>/status/', AnalysisJobStatusView.as_view(), name='analysis-job-status'), # Adjusted path for consistency
    path('jobs/<uuid:job_id>/results/', AnalysisResultView.as_view(), name='analysis-job-results'), # Adjusted path for consistency
    path('types/', AnalysisTypeListView.as_view(), name='analysis-type-list'),
    path('types/<str:analysis_type_name>/', AnalysisTypeDetailView.as_view(), name='analysis-type-detail'),
]
