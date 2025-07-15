from typing import Dict, Type, Any, Optional

STRATEGY_REGISTRY: Dict[str, Type[Any]] = {}
INDICATOR_REGISTRY: Dict[str, Type[Any]] = {}

def register_strategy(name: str, cls: Type[Any]):
    """Registers a strategy class in the global registry."""
    if not hasattr(cls, 'NAME') or cls.NAME != name:
        raise ValueError(f"Strategy class {cls.__name__} NAME attribute must match registration name '{name}'")
    STRATEGY_REGISTRY[name] = cls

def register_indicator(name: str, cls: Type[Any]):
    """Registers an indicator class in the global registry."""
    if not hasattr(cls, 'NAME') or cls.NAME != name:
        raise ValueError(f"Indicator class {cls.__name__} NAME attribute must match registration name '{name}'")
    INDICATOR_REGISTRY[name] = cls

def get_strategy_class(name: str) -> Optional[Type[Any]]:
    """Retrieves a strategy class from the registry by name."""
    return STRATEGY_REGISTRY.get(name)

def get_indicator_class(name: str) -> Optional[Type[Any]]:
    """Retrieves an indicator class from the registry by name."""
    return INDICATOR_REGISTRY.get(name)
