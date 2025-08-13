from django.apps import AppConfig
import importlib
import inspect
import pkgutil
import logging

logger = logging.getLogger(__name__)

class BotsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'bots'

    def ready(self):
        """
        This method is called when the app is ready.
        It's the ideal place to handle app-specific initialization,
        like registering components with a central registry.
        """
        super().ready()
        self._register_components()

    def _register_components(self):
        """
        Discover and register all relevant components from this app.
        """
        from core.registry import operator_registry, action_registry, strategy_registry
        from core.interfaces import OperatorInterface, ActionInterface

        # --- Register Operators ---
        try:
            import bots.nodes.operators
            for name, obj in inspect.getmembers(bots.nodes.operators, inspect.isclass):
                if (hasattr(obj, 'VERSION') and
                    hasattr(obj, 'PARAMS_SCHEMA') and
                    hasattr(obj, 'compute') and
                    obj is not OperatorInterface):
                    operator_registry.register(name, obj)
        except Exception as e:
            logger.error(f"Failed to register operators: {e}", exc_info=True)

        # --- Register Actions ---
        try:
            import bots.nodes.actions
            for name, obj in inspect.getmembers(bots.nodes.actions, inspect.isclass):
                if (hasattr(obj, 'VERSION') and
                    hasattr(obj, 'PARAMS_SCHEMA') and
                    hasattr(obj, 'execute') and
                    obj is not ActionInterface):
                    action_registry.register(name, obj)
        except Exception as e:
            logger.error(f"Failed to register actions: {e}", exc_info=True)

        # --- Register Strategies ---
        try:
            import bots.strategy_templates
            strategy_package_path = bots.strategy_templates.__path__
            for _, name, _ in pkgutil.iter_modules(strategy_package_path):
                try:
                    module = importlib.import_module(f"bots.strategy_templates.{name}")
                    for item_name, item in inspect.getmembers(module, inspect.isclass):
                        if (hasattr(item, 'NAME') and hasattr(item, 'PARAMETERS') and hasattr(item, 'REQUIRED_INDICATORS') and item.__name__ != 'BaseStrategy'):
                            if 'base' in item.__module__:
                                continue
                            strategy_registry.register(item.NAME, item)
                except Exception as e:
                    logger.error(f"Failed to load or register strategy from module '{name}': {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Failed to register strategies: {e}", exc_info=True)
