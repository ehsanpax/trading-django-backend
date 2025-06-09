# Bots services
import hashlib
import importlib
import logging
import uuid
from pathlib import Path # Added for path operations
from django.conf import settings # Added to get BASE_DIR
from django.utils import timezone
from django.core.exceptions import ValidationError

from .models import Bot, BotVersion, LiveRun, BacktestRun, BacktestConfig
from .tasks import live_loop, run_backtest # Import Celery tasks

logger = logging.getLogger(__name__)

def load_strategy_template(strategy_template_name: str):
    """
    Dynamically loads a strategy module/class from bots/strategy_templates/.
    Assumes strategy templates are Python files and contain a class named
    like 'StrategyNameStrategy' or a main 'Strategy' class.
    Example: 'footprint_v1.py' might contain 'FootprintV1Strategy'.
    """
    try:
        module_name = f"bots.strategy_templates.{strategy_template_name.replace('.py', '')}"
        strategy_module = importlib.import_module(module_name)
        
        # Attempt to find a class that likely represents the strategy
        # This is a heuristic; a more robust way is to define a convention,
        # e.g., all strategy files must have a class named 'Strategy'.
        strategy_class_name = None
        if hasattr(strategy_module, 'Strategy'): # Convention: class named Strategy
            strategy_class_name = 'Strategy'
        else: # Heuristic: ClassNameStrategy from filename (e.g. FootprintV1Strategy from footprint_v1.py)
            class_name_parts = [part.capitalize() for part in strategy_template_name.replace('.py', '').split('_')]
            potential_class_name = "".join(class_name_parts) + "Strategy"
            if hasattr(strategy_module, potential_class_name):
                strategy_class_name = potential_class_name
        
        if not strategy_class_name and hasattr(strategy_module, 'FootprintV1Strategy'): # Specific fallback for known strategy
             strategy_class_name = 'FootprintV1Strategy'


        if strategy_class_name:
            return getattr(strategy_module, strategy_class_name)
        else:
            logger.error(f"Could not find a suitable strategy class in module {module_name}.")
            raise ImportError(f"No suitable strategy class found in {strategy_template_name}")

    except ImportError as e:
        logger.error(f"Error loading strategy template '{strategy_template_name}': {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error loading strategy template '{strategy_template_name}': {e}")
        raise

def generate_code_hash(strategy_code: str, params: dict) -> str:
    """
    Generates a SHA256 hash of the strategy code content and its parameters.
    Ensures that params are sorted for consistent hashing.
    """
    hasher = hashlib.sha256()
    hasher.update(strategy_code.encode('utf-8'))
    
    # Sort params by key to ensure consistent hash for the same params regardless of order
    # Convert all param values to string to be safe
    sorted_params_str = "&".join([f"{k}={str(params[k])}" for k in sorted(params.keys())])
    hasher.update(sorted_params_str.encode('utf-8'))
    
    return hasher.hexdigest()

def create_bot_version(bot: Bot, strategy_code: str, params: dict, notes: str = None) -> BotVersion:
    """
    Creates a new BotVersion, calculating its code_hash.
    Prevents duplicate versions for the same bot with identical code & params.
    """
    code_hash = generate_code_hash(strategy_code, params)
    
    existing_version = BotVersion.objects.filter(bot=bot, code_hash=code_hash).first()
    if existing_version:
        logger.info(f"BotVersion with hash {code_hash} already exists for bot {bot.name} (ID: {existing_version.id}). Returning existing.")
        return existing_version # Or raise an error if duplicates are strictly forbidden even if found

    bot_version = BotVersion.objects.create(
        bot=bot,
        code_hash=code_hash,
        params=params,
        notes=notes
    )
    logger.info(f"Created new BotVersion {bot_version.id} for bot {bot.name} with hash {code_hash}")
    return bot_version


def get_strategy_template_content(template_filename: str) -> str:
    """
    Reads and returns the content of a strategy template file.
    """
    try:
        template_path = Path(settings.BASE_DIR) / 'bots' / 'strategy_templates' / template_filename
        if not template_path.is_file():
            logger.error(f"Strategy template file not found: {template_path}")
            raise FileNotFoundError(f"Strategy template file '{template_filename}' not found on server.")
        
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return content
    except Exception as e:
        logger.error(f"Error reading strategy template file '{template_filename}': {e}", exc_info=True)
        raise # Re-raise to be handled by caller

def create_default_bot_version(bot: Bot) -> BotVersion:
    """
    Creates an initial, default BotVersion for a given Bot.
    This version uses the Bot's specified strategy_template file content
    and empty parameters (so the strategy uses its internal defaults).
    """
    logger.info(f"Attempting to create default BotVersion for Bot ID: {bot.id}, Template: {bot.strategy_template}")
    if not bot.strategy_template:
        logger.warning(f"Bot {bot.id} has no strategy_template specified. Cannot create default version.")
        return None 

    try:
        strategy_code_content = get_strategy_template_content(bot.strategy_template)
        default_params = {} # Use empty params to trigger strategy's internal defaults
        notes = "Initial default version automatically created with bot."

        # Call the existing service to create the version
        default_version = create_bot_version(
            bot=bot,
            strategy_code=strategy_code_content,
            params=default_params,
            notes=notes
        )
        logger.info(f"Successfully created default BotVersion {default_version.id} for Bot {bot.id}")
        return default_version
    except FileNotFoundError:
        logger.warning(f"Could not create default BotVersion for Bot {bot.id} because template file '{bot.strategy_template}' was not found.")
        return None
    except Exception as e:
        logger.error(f"Failed to create default BotVersion for Bot {bot.id}: {e}", exc_info=True)
        return None


def start_bot_live_run(bot_version_id: uuid.UUID) -> LiveRun:
    """
    Creates a LiveRun record for the given BotVersion and triggers the live_loop Celery task.
    """
    try:
        bot_version = BotVersion.objects.select_related('bot').get(id=bot_version_id)
        if not bot_version.bot.is_active:
            raise ValidationError(f"Bot {bot_version.bot.name} is not active. Cannot start live run.")
        if not bot_version.bot.account:
            raise ValidationError(f"Bot {bot_version.bot.name} is not assigned to an account. Cannot start live run.")

        # Check for existing active run for this bot version or bot to prevent multiple active runs if desired
        # existing_active_run = LiveRun.objects.filter(bot_version__bot=bot_version.bot, status='RUNNING').first()
        # if existing_active_run:
        #     raise ValidationError(f"Bot {bot_version.bot.name} already has an active live run (ID: {existing_active_run.id}).")

        live_run = LiveRun.objects.create(
            bot_version=bot_version,
            status='PENDING' # Task will set to RUNNING
        )
        logger.info(f"Created LiveRun {live_run.id} for BotVersion {bot_version_id}. Triggering live_loop task.")
        live_loop.delay(live_run.id)
        return live_run
    except BotVersion.DoesNotExist:
        logger.error(f"BotVersion with ID {bot_version_id} not found.")
        raise
    except ValidationError as ve:
        logger.error(f"Validation error starting live run for BotVersion {bot_version_id}: {ve}")
        raise
    except Exception as e:
        logger.error(f"Error starting live run for BotVersion {bot_version_id}: {e}")
        raise

def stop_bot_live_run(live_run_id: uuid.UUID) -> LiveRun:
    """
    Updates LiveRun status to 'STOPPING' or 'STOPPED'.
    The actual stopping mechanism of the Celery task needs consideration (e.g., task checks status).
    """
    try:
        live_run = LiveRun.objects.get(id=live_run_id)
        if live_run.status in ['RUNNING', 'PENDING', 'ERROR']: # Allow stopping if error to mark as user-stopped
            live_run.status = 'STOPPING' # Task should observe this and shut down gracefully
            # live_run.stopped_at = timezone.now() # Or set by task when it actually stops
            live_run.save(update_fields=['status'])
            logger.info(f"LiveRun {live_run.id} status set to STOPPING.")
            # Here, you might need a mechanism to signal the running Celery task if it's long-lived.
            # For periodic tasks, it will simply not be rescheduled or will exit on next run.
            # If live_loop is a very long running task, Celery's revoke might be an option,
            # but it's often better for tasks to be designed to check a stop flag.
        elif live_run.status == 'STOPPING':
             logger.info(f"LiveRun {live_run.id} is already in STOPPING state.")
        else:
            logger.warning(f"LiveRun {live_run.id} is already stopped or in a final state ({live_run.status}).")
        return live_run
    except LiveRun.DoesNotExist:
        logger.error(f"LiveRun with ID {live_run_id} not found.")
        raise
    except Exception as e:
        logger.error(f"Error stopping live run {live_run_id}: {e}")
        raise


def launch_backtest(bot_version_id: uuid.UUID, backtest_config_id: uuid.UUID, 
                    data_window_start: timezone.datetime, data_window_end: timezone.datetime) -> BacktestRun:
    """
    Creates a BacktestRun record and triggers the run_backtest Celery task.
    """
    try:
        bot_version = BotVersion.objects.get(id=bot_version_id)
        config = BacktestConfig.objects.get(id=backtest_config_id, bot_version=bot_version)

        backtest_run = BacktestRun.objects.create(
            config=config,
            data_window_start=data_window_start,
            data_window_end=data_window_end,
            status='PENDING' # Task will set to RUNNING
        )
        logger.info(f"Created BacktestRun {backtest_run.id}. Triggering run_backtest task.")
        run_backtest.delay(backtest_run.id)
        return backtest_run
    except BotVersion.DoesNotExist:
        logger.error(f"BotVersion with ID {bot_version_id} not found for backtest.")
        raise
    except BacktestConfig.DoesNotExist:
        logger.error(f"BacktestConfig with ID {backtest_config_id} not found or not linked to BotVersion {bot_version_id}.")
        raise
    except Exception as e:
        logger.error(f"Error launching backtest for BotVersion {bot_version_id}, Config {backtest_config_id}: {e}")
        raise

# --- Helper/Getter services (placeholders) ---

def get_bot_details(bot_id: uuid.UUID):
    try:
        return Bot.objects.get(id=bot_id)
    except Bot.DoesNotExist:
        logger.warning(f"Bot with ID {bot_id} not found.")
        return None

def get_all_bots_for_user(user):
    return Bot.objects.filter(created_by=user)

def get_bot_versions(bot_id: uuid.UUID):
    return BotVersion.objects.filter(bot_id=bot_id).order_by('-created_at')

def get_backtest_run_results(backtest_run_id: uuid.UUID):
    try:
        return BacktestRun.objects.get(id=backtest_run_id)
    except BacktestRun.DoesNotExist:
        logger.warning(f"BacktestRun with ID {backtest_run_id} not found.")
        return None

def get_live_run_status(live_run_id: uuid.UUID):
    try:
        return LiveRun.objects.get(id=live_run_id)
    except LiveRun.DoesNotExist:
        logger.warning(f"LiveRun with ID {live_run_id} not found.")
        return None
