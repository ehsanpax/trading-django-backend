import logging
import uuid
import sys
import hashlib
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Type, Optional
from django.utils import timezone
from django.core.exceptions import ValidationError

from .models import Bot, BotVersion, LiveRun, BacktestRun, BacktestConfig
from .tasks import live_loop, run_backtest
from core.registry import indicator_registry, strategy_registry
from bots.base import BaseStrategy, BotParameter

logger = logging.getLogger(__name__)

class StrategyManager:
    """
    Manages the loading, validation, and instantiation of strategies and indicators.
    """

    @staticmethod
    def get_available_strategies_metadata() -> List[Dict[str, Any]]:
        """Returns metadata for all registered strategies, including their parameters."""
        metadata = []
        for name, strategy_cls in strategy_registry.get_all_strategies().items():
            params_metadata = []
            for param in strategy_cls.PARAMETERS:
                params_metadata.append({
                    "name": param.name,
                    "parameter_type": param.parameter_type,
                    "display_name": param.display_name,
                    "description": param.description,
                    "default_value": param.default_value,
                    "min_value": param.min_value,
                    "max_value": param.max_value,
                    "step": param.step,
                    "options": param.options,
                })
            metadata.append({
                "name": strategy_cls.NAME,
                "display_name": strategy_cls.DISPLAY_NAME,
                "parameters": params_metadata,
                "required_indicators": strategy_cls.REQUIRED_INDICATORS,
            })
        return metadata

    @staticmethod
    def get_available_indicators_metadata() -> List[Dict[str, Any]]:
        """Returns metadata for all registered indicators, including their parameters."""
        metadata = []
        for name, indicator_cls in indicator_registry.get_all_indicators().items():
            params_list = []
            for param_name, schema in indicator_cls.PARAMS_SCHEMA.items():
                params_list.append({
                    "name": param_name,
                    "parameter_type": schema.get("type"),
                    "display_name": schema.get("display_name"),
                    "description": schema.get("description"),
                    "default_value": schema.get("default"),
                    "min_value": schema.get("min"),
                    "max_value": schema.get("max"),
                    "step": schema.get("step"),
                    "options": schema.get("options") or schema.get("enum"),
                })
            # Enrich with outputs and pane type for frontend output selection and chart placement
            outputs = getattr(indicator_cls, 'OUTPUTS', None) or ["default"]
            pane_type = getattr(indicator_cls, 'PANE_TYPE', 'OVERLAY')
            display_name = getattr(indicator_cls, 'DISPLAY_NAME', name.replace("Indicator", ""))

            metadata.append({
                "name": name,
                "display_name": display_name,
                "parameters": params_list,
                "outputs": outputs,
                "pane_type": pane_type,
            })
        return metadata

    @staticmethod
    def validate_parameters(param_definitions: List[BotParameter], provided_params: Dict[str, Any]):
        """Validates provided parameters against their definitions."""
        for param_def in param_definitions:
            param_name = param_def.name
            if param_name not in provided_params:
                if param_def.default_value is not None:
                    provided_params[param_name] = param_def.default_value
                else:
                    raise ValidationError(f"Missing required parameter: '{param_name}'")

            value = provided_params[param_name]

            if param_def.parameter_type == "int":
                if not isinstance(value, int):
                    try:
                        provided_params[param_name] = int(value)
                    except (ValueError, TypeError):
                        raise ValidationError(f"Parameter '{param_name}' must be an integer.")
            elif param_def.parameter_type == "float":
                if not isinstance(value, (int, float)):
                    try:
                        provided_params[param_name] = float(value)
                    except (ValueError, TypeError):
                        raise ValidationError(f"Parameter '{param_name}' must be a float.")
            elif param_def.parameter_type == "bool":
                if not isinstance(value, bool):
                    raise ValidationError(f"Parameter '{param_name}' must be a boolean.")
            elif param_def.parameter_type == "enum":
                if param_def.options and value not in param_def.options:
                    raise ValidationError(f"Parameter '{param_name}' must be one of {param_def.options}.")

            if param_def.min_value is not None and provided_params[param_name] < param_def.min_value:
                raise ValidationError(f"Parameter '{param_name}' must be at least {param_def.min_value}.")
            if param_def.max_value is not None and provided_params[param_name] > param_def.max_value:
                raise ValidationError(f"Parameter '{param_name}' must be at most {param_def.max_value}.")

    @staticmethod
    def instantiate_strategy(
        strategy_name: str,
        instrument_symbol: str,
        account_id: str,
        instrument_spec: Any,
        strategy_params: Dict[str, Any],
        indicator_configs: List[Dict[str, Any]],
        risk_settings: Dict[str, Any]
    ) -> BaseStrategy:
        """
        Loads and instantiates a strategy with its parameters and required indicators.
        """
        if strategy_name == "SECTIONED_SPEC":
            from .sectioned_adapter import SectionedStrategy
            logger.info("Instantiating SectionedStrategy adapter.")
            # The spec, risk, and filters are all passed within the strategy_params bundle
            return SectionedStrategy(
                instrument_symbol=instrument_symbol,
                account_id=account_id,
                instrument_spec=instrument_spec,
                strategy_params=strategy_params,
                indicator_params=indicator_configs, # May be redundant if adapter handles it
                risk_settings=risk_settings
            )

        strategy_cls = strategy_registry.get_strategy(strategy_name)
        if not strategy_cls:
            raise ValueError(f"Strategy '{strategy_name}' not found in registry.")
        
        StrategyManager.validate_parameters(strategy_cls.PARAMETERS, strategy_params)

        strategy_instance = strategy_cls(
            instrument_symbol=instrument_symbol,
            account_id=account_id,
            instrument_spec=instrument_spec,
            strategy_params=strategy_params,
            indicator_params=indicator_configs,
            risk_settings=risk_settings
        )
        return strategy_instance

def create_bot_version(
    bot: Bot,
    strategy_name: str,
    strategy_params: Dict[str, Any],
    indicator_configs: List[Dict[str, Any]],
    notes: str = None,
    version_name: str = None
) -> BotVersion:
    """
    Creates a new BotVersion, validating strategy and indicator parameters.
    """
    if strategy_name != "SECTIONED_SPEC":
        try:
            strategy_cls = strategy_registry.get_strategy(strategy_name)
            if not strategy_cls:
                raise ValidationError(f"Strategy '{strategy_name}' not found in registry.")
            
            StrategyManager.validate_parameters(strategy_cls.PARAMETERS, strategy_params.copy())

            for ind_config in indicator_configs:
                ind_name = ind_config.get("name")
                ind_params = ind_config.get("params", {})
                indicator_cls = indicator_registry.get_indicator(ind_name)
                # Validation for new indicator format can be added here if needed
                
        except ValidationError as ve:
            logger.error(f"Validation error creating BotVersion: {ve}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during BotVersion validation: {e}", exc_info=True)
            raise ValidationError(f"An unexpected error occurred during validation: {e}")

    bot_version = BotVersion.objects.create(
        bot=bot,
        version_name=version_name,
        strategy_name=strategy_name,
        strategy_params=strategy_params,
        indicator_configs=indicator_configs,
        notes=notes
    )
    logger.info(f"Created new BotVersion {bot_version.id} for bot {bot.name} using strategy '{strategy_name}'")
    return bot_version


def create_default_bot_version(bot: Bot) -> BotVersion:
    """
    Creates an initial, default BotVersion for a given Bot.
    """
    logger.info(f"Attempting to create default BotVersion for Bot ID: {bot.id}")
    
    default_strategy_name = "ema_crossover_v1"
    
    try:
        strategy_cls = strategy_registry.get_strategy(default_strategy_name)
        if not strategy_cls:
            raise ValueError(f"Default strategy '{default_strategy_name}' not found in registry.")
        
        default_strategy_params = {param.name: param.default_value for param in strategy_cls.PARAMETERS}
        
        default_indicator_configs = []
        for req_ind in strategy_cls.REQUIRED_INDICATORS:
            ind_name = req_ind["name"]
            indicator_cls = indicator_registry.get_indicator(ind_name)
            
            resolved_ind_params = {}
            for k, v in req_ind["params"].items():
                if isinstance(v, str) and v in default_strategy_params:
                    resolved_ind_params[k] = default_strategy_params[v]
                else:
                    resolved_ind_params[k] = v
            
            default_indicator_configs.append({
                "name": ind_name,
                "params": resolved_ind_params
            })

        notes = "Initial default version automatically created with bot."

        default_version = create_bot_version(
            bot=bot,
            strategy_name=default_strategy_name,
            strategy_params=default_strategy_params,
            indicator_configs=default_indicator_configs,
            notes=notes
        )
        logger.info(f"Successfully created default BotVersion {default_version.id} for Bot {bot.id}")
        return default_version
    except Exception as e:
        logger.error(f"Failed to create default BotVersion for Bot {bot.id}: {e}", exc_info=True)
        return None


def start_bot_live_run(live_run_id: uuid.UUID) -> LiveRun:
    """
    Triggers the live_loop Celery task for an existing LiveRun record.
    """
    try:
        live_run = LiveRun.objects.select_related('bot_version__bot', 'account').get(id=live_run_id)
        bot_version = live_run.bot_version

        if not bot_version.bot.is_active:
            raise ValidationError(f"Bot {bot_version.bot.name} is not active. Cannot start live run.")
        if not live_run.account:
            raise ValidationError(f"LiveRun {live_run.id} is not associated with an account. Cannot start live run.")

        live_run.status = 'PENDING'
        live_run.save(update_fields=['status'])
        logger.info(f"Created LiveRun {live_run.id} for BotVersion {bot_version.id} on {live_run.instrument_symbol}. Triggering live_loop task.")
        
        live_loop.delay(
            live_run_id=live_run.id,
            strategy_name=bot_version.strategy_name,
            strategy_params=bot_version.strategy_params,
            indicator_configs=bot_version.indicator_configs,
            instrument_symbol=live_run.instrument_symbol,
            account_id=str(live_run.account.id),
            risk_settings={}
        )
        return live_run
    except LiveRun.DoesNotExist:
        logger.error(f"LiveRun with ID {live_run_id} not found.")
        raise
    except ValidationError as ve:
        logger.error(f"Validation error starting live run for LiveRun {live_run_id}: {ve}")
        raise
    except Exception as e:
        logger.error(f"Error starting live run for LiveRun {live_run_id}: {e}", exc_info=True)
        raise

def stop_bot_live_run(live_run_id: uuid.UUID) -> LiveRun:
    """
    Updates LiveRun status to 'STOPPING' or 'STOPPED'.
    """
    try:
        live_run = LiveRun.objects.get(id=live_run_id)
        if live_run.status in ['RUNNING', 'PENDING', 'ERROR']:
            live_run.status = 'STOPPING'
            live_run.save(update_fields=['status'])
            logger.info(f"LiveRun {live_run.id} status set to STOPPING.")
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


def collect_runtime_fingerprint(strategy_name: str) -> Dict[str, Any]:
    """
    Gathers a fingerprint of the runtime environment for reproducibility.
    """
    fingerprint = {
        "python_version": sys.version,
        "numpy_version": np.__version__,
        "pandas_version": pd.__version__,
        "backtest_engine_version": "1.0.0",
    }

    try:
        strategy_cls = strategy_registry.get_strategy(strategy_name)
        if strategy_cls:
            import inspect
            strategy_file_path = inspect.getfile(strategy_cls)
            with open(strategy_file_path, 'rb') as f:
                strategy_hash = hashlib.sha256(f.read()).hexdigest()
            fingerprint["strategy_code_hash"] = strategy_hash
    except (TypeError, FileNotFoundError, ValueError) as e:
        logger.warning(f"Could not generate hash for strategy '{strategy_name}': {e}")
        fingerprint["strategy_code_hash"] = None

    return fingerprint


def launch_backtest(backtest_run_id: uuid.UUID, random_seed: Optional[int] = None) -> BacktestRun:
    """
    Triggers the run_backtest Celery task for an existing BacktestRun record.
    """
    try:
        backtest_run = BacktestRun.objects.select_related('config__bot_version__bot').get(id=backtest_run_id)
        bot_version = backtest_run.config.bot_version

        backtest_run.runtime_fingerprint = collect_runtime_fingerprint(bot_version.strategy_name)
        backtest_run.random_seed = random_seed
        
        backtest_run.status = 'PENDING'
        backtest_run.save(update_fields=['status', 'runtime_fingerprint', 'random_seed'])
        logger.info(f"Created BacktestRun {backtest_run.id} for {backtest_run.instrument_symbol} ({backtest_run.config.timeframe}). Triggering run_backtest task.")
        
        run_backtest.apply_async(
            kwargs={
                "backtest_run_id": backtest_run.id,
                "strategy_name": bot_version.strategy_name,
                "strategy_params": bot_version.strategy_params,
                "indicator_configs": bot_version.indicator_configs,
                "instrument_symbol": backtest_run.instrument_symbol,
                "timeframe": backtest_run.config.timeframe,
                "data_window_start": backtest_run.data_window_start.isoformat(),
                "data_window_end": backtest_run.data_window_end.isoformat(),
                "risk_settings": backtest_run.config.risk_json,
                "random_seed": random_seed,
            },
            queue="backtests"
        )
        return backtest_run
    except BacktestRun.DoesNotExist:
        logger.error(f"BacktestRun with ID {backtest_run_id} not found.")
        raise
    except ValidationError as ve:
        logger.error(f"Validation error launching backtest for BacktestRun {backtest_run_id}: {ve}")
        raise
    except Exception as e:
        logger.error(f"Error launching backtest for BacktestRun {backtest_run_id}: {e}", exc_info=True)
        raise

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
