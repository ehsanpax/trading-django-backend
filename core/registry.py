import importlib
import inspect
import pkgutil
from typing import Dict, Type
import logging

import indicators.definitions
from core.interfaces import IndicatorInterface, OperatorInterface, ActionInterface

logger = logging.getLogger(__name__)

class IndicatorRegistry:
    def __init__(self):
        self._indicators: Dict[str, Type[IndicatorInterface]] = {}
        self.discover_indicators()

    def discover_indicators(self):
        """
        Dynamically discovers and registers indicators from the 'indicators.definitions' package.
        """
        indicator_package_path = indicators.definitions.__path__
        for _, name, _ in pkgutil.iter_modules(indicator_package_path):
            try:
                module = importlib.import_module(f"indicators.definitions.{name}")
                for item_name, item in inspect.getmembers(module, inspect.isclass):
                    # Check if the class has the required attributes and methods of the protocol
                    if (hasattr(item, 'VERSION') and
                        hasattr(item, 'OUTPUTS') and
                        hasattr(item, 'PARAMS_SCHEMA') and
                        hasattr(item, 'compute') and
                        callable(getattr(item, 'compute'))):
                        
                        # Heuristic to avoid registering the protocol itself or base classes
                        if 'interface' in item.__name__.lower() or item.__module__ == 'core.interfaces':
                            continue

                        # Use the NAME attribute if it exists, otherwise fall back to the class name
                        indicator_name = getattr(item, 'NAME', item.__name__)
                        self._indicators[indicator_name] = item
                        logger.info(f"Discovered and registered indicator: {indicator_name}")
            except Exception as e:
                logger.error(f"Failed to load or register indicator from module '{name}': {e}", exc_info=True)

    def get_indicator(self, name: str) -> Type[IndicatorInterface]:
        """
        Retrieves an indicator class from the registry.
        """
        indicator = self._indicators.get(name)
        if not indicator:
            raise ValueError(f"Indicator '{name}' not found in registry.")
        return indicator

    def get_all_indicators(self) -> Dict[str, Type[IndicatorInterface]]:
        """
        Returns all registered indicators.
        """
        return self._indicators

# Global instance of the registry
indicator_registry = IndicatorRegistry()


class OperatorRegistry:
    def __init__(self):
        self._operators: Dict[str, Type[OperatorInterface]] = {}

    def register(self, name: str, operator_cls: Type[OperatorInterface]):
        """Registers a single operator class."""
        if name in self._operators:
            logger.warning(f"Operator '{name}' is being re-registered.")
        self._operators[name] = operator_cls
        logger.info(f"Registered operator: {name}")

    def get_operator(self, name: str) -> Type[OperatorInterface]:
        operator = self._operators.get(name)
        if not operator:
            raise ValueError(f"Operator '{name}' not found in registry.")
        return operator

    def get_all_operators(self) -> Dict[str, Type[OperatorInterface]]:
        return self._operators

operator_registry = OperatorRegistry()


class ActionRegistry:
    def __init__(self):
        self._actions: Dict[str, Type[ActionInterface]] = {}

    def register(self, name: str, action_cls: Type[ActionInterface]):
        """Registers a single action class."""
        if name in self._actions:
            logger.warning(f"Action '{name}' is being re-registered.")
        self._actions[name] = action_cls
        logger.info(f"Registered action: {name}")

    def get_action(self, name: str) -> Type[ActionInterface]:
        action = self._actions.get(name)
        if not action:
            raise ValueError(f"Action '{name}' not found in registry.")
        return action

    def get_all_actions(self) -> Dict[str, Type[ActionInterface]]:
        return self._actions

action_registry = ActionRegistry()


class StrategyRegistry:
    def __init__(self):
        self._strategies: Dict[str, Type] = {}

    def register(self, name: str, strategy_cls: Type):
        """Registers a single strategy class."""
        if name in self._strategies:
            logger.warning(f"Strategy '{name}' is being re-registered.")
        self._strategies[name] = strategy_cls
        logger.info(f"Registered strategy: {name}")

    def get_strategy(self, name: str) -> Type:
        """
        Retrieves a strategy class from the registry.
        """
        strategy = self._strategies.get(name)
        if not strategy:
            raise ValueError(f"Strategy '{name}' not found in registry.")
        return strategy

    def get_all_strategies(self) -> Dict[str, Type]:
        """
        Returns all registered strategies.
        """
        return self._strategies

strategy_registry = StrategyRegistry()
