import uuid # Added for generating unique file names
import requests
import logging
from celery import shared_task
from django.conf import settings
from django.core.files.base import ContentFile
from .models import ChartSnapshotConfig, ChartSnapshot
from .utils import build_chart_img_payload, API_BASE_URL
from trade_journal.models import TradeJournalAttachment, TradeJournal # For linking

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def generate_chart_snapshot_task(self, config_id=None, journal_entry_id=None, adhoc_settings=None):
    """
    Celery task to generate a chart snapshot from chart-img.com,
    store it as a TradeJournalAttachment, and create a ChartSnapshot record.
    Can be triggered by a config_id or adhoc_settings.
    """
    config = None
    snapshot_symbol = None
    snapshot_timeframe = None
    indicator_settings_payload = None

    if config_id:
        try:
            config = ChartSnapshotConfig.objects.get(id=config_id)
            # If adhoc_settings are also provided (e.g. from execute_snapshot view),
            # they dictate the actual chart parameters. config is just for linking.
            if adhoc_settings:
                snapshot_symbol = adhoc_settings.get("symbol")
                snapshot_timeframe = adhoc_settings.get("timeframe")
                indicator_settings_payload = adhoc_settings.get("indicator_settings") # These came from config in the view
            else:
                # This case implies a direct task call with config_id only,
                # which is no longer supported as config doesn't store symbol/timeframe.
                # Such a call would be an error in the calling code.
                logger.error(f"Task called with config_id {config_id} but without adhoc_settings providing symbol/timeframe.")
                return f"Symbol/timeframe must be provided (via adhoc_settings) when using config_id {config_id}."
        except ChartSnapshotConfig.DoesNotExist:
            logger.error(f"ChartSnapshotConfig with id {config_id} not found.")
            return f"Config ID {config_id} not found."
    elif adhoc_settings: # Called without config_id, purely ad-hoc
        snapshot_symbol = adhoc_settings.get("symbol")
        snapshot_timeframe = adhoc_settings.get("timeframe")
        indicator_settings_payload = adhoc_settings.get("indicator_settings")
    
    # Validate that we have all necessary parameters for the payload
    if not all([snapshot_symbol, snapshot_timeframe, indicator_settings_payload]):
        logger.error(f"Insufficient parameters for chart generation. Symbol: {snapshot_symbol}, Timeframe: {snapshot_timeframe}, Indicators: {indicator_settings_payload is not None}")
        return "Insufficient parameters for chart generation (symbol, timeframe, or indicator_settings missing)."
    
    api_key = getattr(settings, 'CHART_IMG_API_KEY', None)
    if not api_key:
        logger.error("CHART_IMG_API_KEY not configured in Django settings.")
        # Do not retry for configuration errors
        return "CHART_IMG_API_KEY not configured."

    payload = build_chart_img_payload(snapshot_symbol, snapshot_timeframe, indicator_settings_payload)
    headers = {
        'x-api-key': api_key,
        'Content-Type': 'application/json'
    }

    logger.info(f"Chart-img.com API Request Payload: {payload}") # Log the payload

    try:
        response = requests.post(API_BASE_URL, json=payload, headers=headers, timeout=30) # 30 second timeout
        # Log response content for debugging 422 errors, if possible
        try:
            response_json = response.json()
            logger.info(f"Chart-img.com API Response (status {response.status_code}):")
        except requests.exceptions.JSONDecodeError:
            logger.info(f"Chart-img.com API Response (status {response.status_code}, not JSON)")

        response.raise_for_status()  # Raise HTTPError for bad responses (4XX or 5XX)
    
    except requests.exceptions.Timeout:
        log_ctx = f"config {config_id}" if config_id else "adhoc snapshot"
        logger.warning(f"Timeout requesting chart from chart-img.com for {log_ctx}. Retrying...")
        raise self.retry(exc=requests.exceptions.Timeout(f"Chart-img.com timeout for {log_ctx}"))
    except requests.exceptions.RequestException as e:
        log_ctx = f"config {config_id}" if config_id else "adhoc snapshot"
        logger.error(f"Error requesting chart from chart-img.com for {log_ctx}: {e}")
        # Retry for generic request exceptions (like network issues)
        raise self.retry(exc=e)

    # Image content is in response.content
    image_content = response.content
    image_name = f"chart_snapshot_{snapshot_symbol}_{snapshot_timeframe}_{uuid.uuid4().hex[:8]}.png"

    # Determine the journal entry
    journal = None
    if journal_entry_id:
        try:
            journal = TradeJournal.objects.get(id=journal_entry_id)
        except TradeJournal.DoesNotExist:
            log_ctx = f"config {config_id}" if config_id else "adhoc snapshot"
            logger.warning(f"TradeJournal entry with id {journal_entry_id} not found for {log_ctx}. Snapshot will be created without journal link.")
    
    # Create TradeJournalAttachment
    attachment = TradeJournalAttachment()
    if journal:
        attachment.journal = journal
    # If no journal, the attachment will be orphaned or you might decide not to create it,
    # or link it directly to the ChartSnapshot if your models allow.
    # For now, we create it, and it can be linked to a journal later if needed,
    # or the ChartSnapshot model can have a direct FileField if preferred for unlinked snapshots.
    # Based on current plan, ChartSnapshot links to TradeJournalAttachment.
    # If journal_id is None, the attachment.journal will be None.
    # This might require the journal field on TradeJournalAttachment to be nullable,
    # or we ensure journal_entry_id is always passed if an attachment is to be made.
    # For now, assuming attachment.journal can be null or ChartSnapshot is the primary link.
    # Let's ensure attachment is created even without a journal for now,
    # as the snapshot itself is valuable.
    # The ChartSnapshot model has a OneToOne to attachment, so attachment must be saved first.

    # If TradeJournalAttachment.journal cannot be null, we must handle this.
    # Let's assume for now that if journal_entry_id is None, we might not create
    # the TradeJournalAttachment OR the ChartSnapshot needs its own FileField.
    # Given the current models, ChartSnapshot REQUIRES an attachment.
    # And TradeJournalAttachment REQUIRES a journal. This is a conflict if journal_entry_id is None.

    # Simplification: For now, let's assume journal_entry_id will be provided if a snapshot is tied to a journal.
    # If a snapshot is generated from config without immediate journal link, how to store image?
    # Option 1: ChartSnapshot gets its own FileField.
    # Option 2: TradeJournalAttachment.journal becomes nullable. (Chosen in models.py implicitly by not setting null=False)
    # Let's check trade_journal.models.TradeJournalAttachment.journal field.
    # It is: journal = models.ForeignKey(TradeJournal, on_delete=models.CASCADE, related_name="attachments")
    # This means journal_id cannot be NULL unless null=True is added to the ForeignKey.
    # For now, let's proceed assuming journal_entry_id is always available for this task,
    # or that the model will be adjusted. If not, this task will fail for journal_entry_id=None.
    # TradeJournalAttachment.journal is now nullable, so we can create an attachment
    # even if journal is None.
    attachment.file.save(image_name, ContentFile(image_content), save=True) # Save attachment first

    # Create ChartSnapshot record
    snapshot = ChartSnapshot.objects.create(
        config=config, # This will be None for adhoc snapshots
        journal_entry=journal, 
        attachment=attachment,
        symbol=snapshot_symbol, 
        timeframe=snapshot_timeframe
        # notes can be added later if needed
    )
    log_ctx_config = f"config {config.id}" if config else "adhoc settings"
    logger.info(f"Successfully created chart snapshot {snapshot.id} using {log_ctx_config} (Journal ID: {journal.id if journal else 'None'})")
    return f"Snapshot {snapshot.id} created."
