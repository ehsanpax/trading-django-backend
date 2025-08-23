import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone

class Instrument(models.Model):
    DATA_STATUS_CHOICES = [
        ('PENDING_INITIAL_DOWNLOAD', 'Pending Initial Download'),
        ('AVAILABLE', 'Available'),
        ('UPDATING', 'Updating'),
        ('ERROR', 'Error'),
    ]
    symbol = models.CharField(max_length=50, unique=True)
    exchange = models.CharField(max_length=50, default="FXCM")
    base_timeframe = models.CharField(max_length=10, default="M1")
    last_updated = models.DateTimeField(null=True, blank=True)
    data_status = models.CharField(max_length=30, choices=DATA_STATUS_CHOICES, default='PENDING_INITIAL_DOWNLOAD') # Increased max_length for 'PENDING_INITIAL_DOWNLOAD'
    is_major = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.symbol} ({self.exchange})"

class AnalysisJob(models.Model):
    ANALYSIS_TYPE_CHOICES = [
        ('TREND_CONTINUATION', 'Trend Continuation'),
        ('VWAP_CONDITIONAL', 'VWAP Conditional'),
        ('ATR_SCENARIO', 'ATR Scenario'),
        ('ATR_SQUEEZE_BREAKOUT', 'ATR Squeeze Breakout'),
        # Add more choices as they are defined
    ]
    JOB_STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('FETCHING_DATA', 'Fetching Data'),
        ('RESAMPLING_DATA', 'Resampling Data'),
        ('CALCULATING_INDICATORS', 'Calculating Indicators'),
        ('RUNNING_ANALYSIS', 'Running Analysis'),
        ('COMPLETED_SUCCESS', 'Completed Successfully'), # Adjusted for clarity
        ('COMPLETED_FAIL', 'Completed with Failure'),   # Adjusted for clarity
    ]

    job_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, blank=True, null=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE) # Changed to CASCADE as PROTECT might be too restrictive if user is deleted
    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT)
    analysis_type = models.CharField(max_length=100, choices=ANALYSIS_TYPE_CHOICES)
    target_timeframe = models.CharField(max_length=10)
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=30, choices=JOB_STATUS_CHOICES, default='PENDING')
    indicator_configs = models.JSONField(default=list, blank=True)
    analysis_params = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    error_message = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"Job {self.job_id} for {self.instrument.symbol} ({self.analysis_type})"

class AnalysisResult(models.Model):
    job = models.OneToOneField(AnalysisJob, on_delete=models.CASCADE, primary_key=True)
    result_data = models.JSONField()
    generated_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Result for Job {self.job_id}"
