# Celery tasks for the analysis app will be defined here.
# This file is initially created to allow imports in views.py.
import uuid
from datetime import datetime, timedelta, timezone as dt_timezone # Import timezone explicitly
from pathlib import Path
from django.conf import settings
from django.db import models # Added for Q objects
from celery import shared_task
from .models import AnalysisJob, Instrument, AnalysisResult
from django.utils import timezone
import logging
import pandas as pd # Added for pd.Timestamp

from .utils import data_fetcher, data_processor # Import actual utilities
from bots.registry import get_indicator_class
# from ..analysis import core_analysis # This import might be problematic due to relative path, direct import of modules is better
import importlib


logger = logging.getLogger(__name__)

# Mapping from analysis_type in model to module name in core_analysis
ANALYSIS_MODULE_MAPPING = {
    'TREND_CONTINUATION': 'trend_continuation',
    'VWAP_CONDITIONAL': 'vwap_conditional',
    'ATR_SCENARIO': 'atr_scenario',
    'ATR_SQUEEZE_BREAKOUT': 'atr_squeeze_breakout',
}


@shared_task
def fetch_missing_instrument_data_task(instrument_symbol, job_id_str):
    job_id = uuid.UUID(job_id_str) # Convert string back to UUID
    logger.info(f"Task fetch_missing_instrument_data_task started for {instrument_symbol}, job {job_id}")
    job = None
    try:
        job = AnalysisJob.objects.get(job_id=job_id)
        instrument = job.instrument

        job.status = 'FETCHING_DATA'
        job.save()

        # Determine the range for initial history.
        # This might need a default start date if not specified elsewhere, e.g., 2 years ago.
        # For now, let's assume a fixed period or it's derived from job if applicable.
        # The original `download_initial_history` task had a start_date_str.
        # Here, we might need to define a policy, e.g., fetch last N years for initial download.
        # Let's use job's start_date as a reference, or a default if job is very recent.
        
        # Default: Fetch data from job's start_date up to now.
        # A more robust approach might be to fetch a standard historical depth (e.g., 5 years)
        # if the instrument has PENDING_INITIAL_DOWNLOAD status.
        # For now, using job.start_date.
        
        # Ensure start_date and end_date are timezone-aware datetimes for data_fetcher
        start_dt = datetime.combine(job.start_date, datetime.min.time()).replace(tzinfo=dt_timezone.utc)
        # Fetch a bit more to ensure coverage, or up to 'now' for initial full fetch
        end_dt = timezone.now() # Fetch up to current time for initial download

        logger.info(f"Fetching initial history for {instrument.symbol} from {start_dt} to {end_dt}")
        
        historical_df = data_fetcher.get_historical_m1_data(instrument.symbol, start_dt, end_dt)

        if not historical_df.empty:
            # Store data to Parquet
            # This part needs a function in data_processor, e.g., save_m1_data_to_parquet
            # For now, let's assume data_processor handles this.
            # data_processor.save_m1_data_to_parquet(instrument.symbol, historical_df) # Needs implementation
            
            # Create dummy Parquet file for now to allow flow
            data_root = Path(settings.DATA_ROOT)
            parquet_file_path = data_root / instrument.symbol / "M1.parquet"
            parquet_file_path.parent.mkdir(parents=True, exist_ok=True)
            if not historical_df.empty:
                 historical_df.to_parquet(parquet_file_path)
                 logger.info(f"Saved initial data for {instrument.symbol} to {parquet_file_path}")


            instrument.last_updated = timezone.now()
            instrument.data_status = 'AVAILABLE'
            instrument.save()
            logger.info(f"Instrument {instrument.symbol} data status updated to AVAILABLE.")

            # Once data is fetched, trigger the analysis job
            job.status = 'PENDING' # Reset to PENDING so run_analysis_job_task can pick it up
            job.save()
            run_analysis_job_task.delay(str(job.job_id)) # Call the main analysis task
        else:
            logger.error(f"Failed to fetch initial historical data for {instrument.symbol}.")
            instrument.data_status = 'ERROR'
            instrument.save()
            if job:
                job.status = 'COMPLETED_FAIL'
                job.error_message = f"Failed to fetch initial historical data for {instrument.symbol}."
                job.save()

    except Instrument.DoesNotExist:
        logger.error(f"Instrument {instrument_symbol} not found during fetch_missing_instrument_data_task.")
        if job:
            job.status = 'COMPLETED_FAIL'
            job.error_message = f"Instrument {instrument_symbol} not found."
            job.save()
    except AnalysisJob.DoesNotExist:
         logger.error(f"AnalysisJob {job_id} not found during fetch_missing_instrument_data_task.")
    except Exception as e:
        logger.error(f"Error in fetch_missing_instrument_data_task for {instrument_symbol}, job {job_id}: {e}", exc_info=True)
        if job:
            job.status = 'COMPLETED_FAIL'
            job.error_message = str(e)
            job.save()
        # Also update instrument status if appropriate
        try:
            instrument_obj = Instrument.objects.get(symbol=instrument_symbol)
            instrument_obj.data_status = 'ERROR'
            instrument_obj.save()
        except Instrument.DoesNotExist:
            pass


@shared_task
def download_initial_history_task(instrument_symbol, start_date_str):
    """ This task is for general data acquisition, not tied to a specific job initially """
    logger.info(f"Task download_initial_history_task started for {instrument_symbol} from {start_date_str}")
    try:
        instrument = Instrument.objects.get(symbol=instrument_symbol)
        instrument.data_status = 'UPDATING' # Or FETCHING_DATA
        instrument.save()

        parsed_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        start_dt = parsed_date.replace(tzinfo=dt_timezone.utc) # Corrected timezone.utc
        end_dt = timezone.now()

        historical_df = data_fetcher.get_historical_m1_data(instrument.symbol, start_dt, end_dt)

        if not historical_df.empty:
            # data_processor.save_m1_data_to_parquet(instrument.symbol, historical_df) # Needs implementation
            data_root = Path(settings.DATA_ROOT)
            parquet_file_path = data_root / instrument.symbol / "M1.parquet"
            parquet_file_path.parent.mkdir(parents=True, exist_ok=True)
            historical_df.to_parquet(parquet_file_path) # Overwrites if exists
            logger.info(f"Saved/Updated data for {instrument.symbol} to {parquet_file_path}")

            instrument.last_updated = timezone.now()
            instrument.data_status = 'AVAILABLE'
            instrument.save()
            logger.info(f"Initial history download complete for {instrument.symbol}.")
        else:
            logger.error(f"No data returned from fetch for {instrument.symbol} in download_initial_history_task.")
            instrument.data_status = 'ERROR'
            instrument.save()

    except Instrument.DoesNotExist:
        logger.error(f"Instrument {instrument_symbol} not found for initial history download.")
    except Exception as e:
        logger.error(f"Error in download_initial_history_task for {instrument_symbol}: {e}", exc_info=True)
        try:
            instrument = Instrument.objects.get(symbol=instrument_symbol)
            instrument.data_status = 'ERROR'
            instrument.save()
        except Instrument.DoesNotExist:
            pass


@shared_task
def update_daily_history_task():
    logger.info(f"Task update_daily_history_task started")
    # Query instruments that need daily updates (is_major=True or AVAILABLE and not updated recently)
    # For simplicity, let's try to update all 'AVAILABLE' or 'UPDATING' instruments.
    instruments_to_update = Instrument.objects.filter(
        models.Q(data_status='AVAILABLE') | models.Q(data_status='UPDATING') | models.Q(is_major=True)
    ).distinct()

    for instrument in instruments_to_update:
        try:
            logger.info(f"Updating daily history for {instrument.symbol}")
            last_known_timestamp = instrument.last_updated or (timezone.now() - timedelta(days=365*2)) # Fallback to 2 years ago if never updated
            
            # Ensure last_known_timestamp is timezone-aware
            if timezone.is_naive(last_known_timestamp): # Naive means no tzinfo
                last_known_timestamp = last_known_timestamp.replace(tzinfo=dt_timezone.utc) # Assign UTC if naive
            elif last_known_timestamp.tzinfo != dt_timezone.utc: # If it has tzinfo but not UTC, convert
                last_known_timestamp = last_known_timestamp.astimezone(dt_timezone.utc)


            new_data_df = data_fetcher.get_latest_m1_data(instrument.symbol, last_known_timestamp)

            if not new_data_df.empty:
                # data_processor.append_m1_data_to_parquet(instrument.symbol, new_data_df) # Needs implementation
                # For now, simple save/overwrite for testing, append logic is more complex
                data_root = Path(settings.DATA_ROOT)
                parquet_file_path = data_root / instrument.symbol / "M1.parquet"
                parquet_file_path.parent.mkdir(parents=True, exist_ok=True)
                
                if parquet_file_path.exists():
                    existing_df = pd.read_parquet(parquet_file_path)
                    combined_df = pd.concat([existing_df, new_data_df])
                    combined_df = combined_df[~combined_df.index.duplicated(keep='last')] # Keep last to update with fresh data
                    combined_df.sort_index(inplace=True)
                    combined_df.to_parquet(parquet_file_path)
                else:
                    new_data_df.to_parquet(parquet_file_path)
                logger.info(f"Appended new data for {instrument.symbol} to {parquet_file_path}")


                instrument.last_updated = timezone.now()
                # instrument.data_status = 'AVAILABLE' # Should already be available or updating
                instrument.save()
                logger.info(f"Daily history update complete for {instrument.symbol}.")
            else:
                logger.info(f"No new data found for {instrument.symbol} since {last_known_timestamp}.")
                # Optionally update last_updated anyway to prevent constant re-checking if no data is normal
                instrument.last_updated = timezone.now() 
                instrument.save()

        except Exception as e:
            logger.error(f"Error updating daily history for {instrument.symbol}: {e}", exc_info=True)
            instrument.data_status = 'ERROR' # Mark as error if update fails
            instrument.save()


@shared_task
def calculate_indicators_dynamically(df: pd.DataFrame, indicator_configs: list) -> pd.DataFrame:
    """
    Calculates indicators on a DataFrame based on a list of configurations.
    """
    if not indicator_configs:
        return df

    df_with_indicators = df.copy()
    for config in indicator_configs:
        indicator_name = config.get('name')
        params = config.get('params', {})
        output_name = config.get('output_name')

        if not indicator_name:
            logger.warning("Skipping indicator config because 'name' is missing.")
            continue

        IndicatorClass = get_indicator_class(indicator_name)
        if not IndicatorClass:
            logger.error(f"Indicator '{indicator_name}' not found in registry.")
            continue

        indicator_instance = IndicatorClass()

        # --- Start of new logic for type conversion ---
        typed_params = {}
        for param_def in indicator_instance.PARAMETERS:
            param_name = param_def.name
            if param_name in params:
                value = params[param_name]
                param_type = param_def.parameter_type
                try:
                    if param_type == 'int':
                        typed_params[param_name] = int(value)
                    elif param_type == 'float':
                        typed_params[param_name] = float(value)
                    else:
                        typed_params[param_name] = value # Keep as string for 'enum', etc.
                except (ValueError, TypeError):
                    logger.warning(f"Could not convert param '{param_name}' with value '{value}' to type '{param_type}'. Using default.")
                    typed_params[param_name] = param_def.default_value
            else:
                typed_params[param_name] = param_def.default_value
        # --- End of new logic ---

        # Store original columns to identify the new one
        original_columns = set(df_with_indicators.columns)
        
        df_with_indicators = indicator_instance.calculate(df_with_indicators, **typed_params)
        
        # Identify the newly added column
        new_columns = set(df_with_indicators.columns) - original_columns
        if len(new_columns) == 1:
            new_column_name = new_columns.pop()
            if output_name and new_column_name != output_name:
                df_with_indicators.rename(columns={new_column_name: output_name}, inplace=True)
                logger.info(f"Calculated {indicator_name} and renamed column to {output_name}")
        elif len(new_columns) > 1:
            logger.warning(f"Indicator {indicator_name} added multiple columns. Renaming with output_name is not supported in this case.")
        elif len(new_columns) == 0:
            logger.warning(f"Indicator {indicator_name} did not add any new columns.")

    return df_with_indicators


@shared_task
def run_analysis_job_task(job_id_str):
    job_id = uuid.UUID(job_id_str) # Convert string back to UUID
    logger.info(f"Task run_analysis_job_task started for job {job_id}")
    job = None
    try:
        job = AnalysisJob.objects.get(job_id=job_id)
        
        # Check if data is actually available before proceeding
        if job.instrument.data_status != 'AVAILABLE':
            # This case might happen if fetch_missing_instrument_data_task failed silently
            # or if status was manually changed.
            # Re-trigger data fetching or fail the job.
            if job.instrument.data_status in ['PENDING_INITIAL_DOWNLOAD', 'ERROR']:
                logger.warning(f"Data for {job.instrument.symbol} is {job.instrument.data_status}. Re-triggering fetch for job {job_id}.")
                job.status = 'FETCHING_DATA' # Set status back
                job.save()
                fetch_missing_instrument_data_task.delay(job.instrument.symbol, str(job.job_id))
                return # Exit this task, let the fetch task handle it.
            else: # e.g. UPDATING, could wait or proceed cautiously
                logger.warning(f"Data for {job.instrument.symbol} is {job.instrument.data_status}. Proceeding with caution for job {job_id}.")


        job.status = 'RESAMPLING_DATA'
        job.save()

        # 1. Load M1 data for the required period
        # Ensure start_date and end_date are proper Timestamps for data_processor
        start_ts = pd.Timestamp(job.start_date, tz='UTC')
        # For end_date, make it inclusive of the whole day for filtering
        end_ts = pd.Timestamp(job.end_date, tz='UTC') + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)

        m1_df = data_processor.load_m1_data_from_parquet(job.instrument.symbol, start_ts, end_ts)
        if m1_df.empty:
            logger.warning(f"No M1 data found for {job.instrument.symbol} between {job.start_date} and {job.end_date}. Triggering data fetch.")
            job.status = 'FETCHING_DATA'
            job.save()
            fetch_missing_instrument_data_task.delay(job.instrument.symbol, str(job.job_id))
            return

        # 2. Resample data to target timeframe
        resampled_df = data_processor.resample_data(m1_df, job.target_timeframe)
        if resampled_df.empty:
            raise ValueError(f"Data resampling to {job.target_timeframe} resulted in an empty DataFrame.")

        job.status = 'CALCULATING_INDICATORS'
        job.save()
        # 3. Calculate indicators dynamically
        df_with_indicators = calculate_indicators_dynamically(resampled_df, job.indicator_configs)

        job.status = 'RUNNING_ANALYSIS'
        job.save()
        # 4. Dynamically call the analysis module
        analysis_module_name = ANALYSIS_MODULE_MAPPING.get(job.analysis_type)
        if not analysis_module_name:
            raise ValueError(f"No analysis module mapped for analysis type: {job.analysis_type}")

        try:
            # Path to the module, e.g., analysis.core_analysis.trend_continuation
            module_path = f"analysis.core_analysis.{analysis_module_name}"
            analysis_module = importlib.import_module(module_path)
        except ImportError:
            logger.error(f"Could not import analysis module: {module_path}", exc_info=True)
            raise ValueError(f"Analysis module {analysis_module_name} not found.")

        if not hasattr(analysis_module, 'run_analysis'):
            raise AttributeError(f"Analysis module {analysis_module_name} does not have a 'run_analysis' function.")

        # Prepare parameters for the analysis function
        analysis_params = job.analysis_params
        
        logger.info(f"Calling {analysis_module_name}.run_analysis for job {job_id}")
        analysis_result_data = analysis_module.run_analysis(df_with_indicators, **analysis_params)
        
        # 5. Store results
        AnalysisResult.objects.create(
            job=job,
            result_data=analysis_result_data
        )
        job.status = 'COMPLETED_SUCCESS'
        job.save()
        logger.info(f"Job {job_id} ({job.analysis_type} for {job.instrument.symbol}) completed successfully.")

    except AnalysisJob.DoesNotExist:
        logger.error(f"AnalysisJob with id {job_id} not found.")
    except Exception as e:
        logger.error(f"Error running analysis job {job_id}: {e}", exc_info=True)
        if job: # Ensure job is defined
            try:
                # Check if job still exists before trying to save
                job_exists = AnalysisJob.objects.filter(job_id=job_id).exists()
                if job_exists:
                    job.status = 'COMPLETED_FAIL'
                    job.error_message = str(e)
                    job.save()
                else:
                    logger.warning(f"Job {job_id} was deleted or not found during error handling.")
            except Exception as save_err:
                 logger.error(f"Further error saving job {job_id} status after failure: {save_err}", exc_info=True)
