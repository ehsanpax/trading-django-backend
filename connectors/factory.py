# connectors/factory.py
"""
Platform-agnostic connector factory that provides standardized trading platform interfaces.
This factory abstracts the creation of platform-specific connectors and provides a unified
interface for all trading operations.

New platform integrations only need to:
1. Implement the TradingPlatformConnector interface
2. Register their connector class in the CONNECTOR_REGISTRY
3. Provide credential mapping logic
"""

import logging
from typing import Dict, Type, Any
from django.conf import settings
from django.shortcuts import get_object_or_404

from accounts.models import MT5Account, CTraderAccount, Account
from .base import TradingPlatformConnector
from .mt5_connector import MT5Connector
from .ctrader_http_connector import CTraderHTTPConnector

logger = logging.getLogger(__name__)


class ConnectorRegistry:
    """Registry for managing available trading platform connectors"""
    
    def __init__(self):
        self._connectors: Dict[str, Type[TradingPlatformConnector]] = {}
        self._credential_mappers: Dict[str, callable] = {}
    
    def register(
        self, 
        platform_name: str, 
        connector_class: Type[TradingPlatformConnector],
        credential_mapper: callable
    ):
        """
        Register a new trading platform connector.
        
        Args:
            platform_name: Name of the platform (e.g., "MT5", "cTrader")
            connector_class: Class implementing TradingPlatformConnector
            credential_mapper: Function to map Account to connector credentials
        """
        platform_key = platform_name.upper()
        self._connectors[platform_key] = connector_class
        self._credential_mappers[platform_key] = credential_mapper
        logger.info(f"Registered connector for platform: {platform_name}")
    
    def get_connector_class(self, platform: str) -> Type[TradingPlatformConnector]:
        """Get connector class for platform"""
        platform_key = platform.upper()
        if platform_key not in self._connectors:
            raise ValueError(f"No connector registered for platform: {platform}")
        return self._connectors[platform_key]
    
    def get_credential_mapper(self, platform: str) -> callable:
        """Get credential mapper for platform"""
        platform_key = platform.upper()
        if platform_key not in self._credential_mappers:
            raise ValueError(f"No credential mapper registered for platform: {platform}")
        return self._credential_mappers[platform_key]
    
    def get_supported_platforms(self) -> list:
        """Get list of all registered platforms"""
        return list(self._connectors.keys())


# Global registry instance
_registry = ConnectorRegistry()


def register_connector(
    platform_name: str, 
    connector_class: Type[TradingPlatformConnector],
    credential_mapper: callable
):
    """
    Decorator and function to register trading platform connectors.
    
    Usage:
        @register_connector("NewPlatform", credential_mapper_func)
        class NewPlatformConnector(TradingPlatformConnector):
            # Implementation
    """
    def decorator(cls):
        _registry.register(platform_name, cls, credential_mapper)
        return cls
    
    if connector_class is not None:
        # Function call usage
        _registry.register(platform_name, connector_class, credential_mapper)
        return connector_class
    else:
        # Decorator usage
        return decorator


# Credential mapping functions for each platform
def map_mt5_credentials(account: Account) -> Dict[str, Any]:
    """Map Account to MT5 connector credentials"""
    mt5_acc = get_object_or_404(MT5Account, account=account)
    return {
        'base_url': settings.MT5_API_BASE_URL,
        'account_id': mt5_acc.account_number,
        'password': mt5_acc.encrypted_password,
        'broker_server': mt5_acc.broker_server,
        'internal_account_id': str(account.id),
    }


def map_ctrader_credentials(account: Account) -> Dict[str, Any]:
    """Map Account to cTrader connector credentials"""
    ct_acc = get_object_or_404(CTraderAccount, account=account)
    return {
        'account_id': ct_acc.ctid_trader_account_id,
        'access_token': ct_acc.access_token,
        'refresh_token': ct_acc.refresh_token,
        'is_sandbox': ct_acc.is_sandbox,
        'ctid_user_id': ct_acc.ctid_user_id,
        'internal_account_id': str(account.id),
    }


# Register built-in connectors
register_connector("MT5", MT5Connector, map_mt5_credentials)

# Register cTrader HTTP-based connector (microservice-backed)
register_connector("cTrader", CTraderHTTPConnector, map_ctrader_credentials)


def get_connector(account: Account) -> TradingPlatformConnector:
    """
    Factory function to create a standardized connector for any trading platform.
    
    Args:
        account: Account instance with platform information
        
    Returns:
        TradingPlatformConnector: Platform-specific connector implementing standard interface
        
    Raises:
        ValueError: If platform is not supported
    """
    platform = (account.platform or "").strip()
    
    if not platform:
        raise ValueError("Account platform is not specified")
    
    try:
        connector_class = _registry.get_connector_class(platform)
        credential_mapper = _registry.get_credential_mapper(platform)
        
        credentials = credential_mapper(account)
        return connector_class(credentials)
        
    except ValueError as e:
        supported_platforms = _registry.get_supported_platforms()
        raise ValueError(
            f"Unsupported platform: {platform}. "
            f"Supported platforms: {supported_platforms}"
        ) from e


async def get_connector_async(account: Account) -> TradingPlatformConnector:
    """Async-safe version of get_connector that uses async ORM for credentials."""
    platform = (account.platform or "").strip()

    if not platform:
        raise ValueError("Account platform is not specified")

    connector_class = _registry.get_connector_class(platform)

    platform_upper = platform.upper()
    if platform_upper == "MT5":
        try:
            mt5_acc = await MT5Account.objects.aget(account=account)
        except MT5Account.DoesNotExist as e:
            raise ValueError("No linked MT5 account found.") from e
        credentials = {
            'base_url': settings.MT5_API_BASE_URL,
            'account_id': mt5_acc.account_number,
            'password': mt5_acc.encrypted_password,
            'broker_server': mt5_acc.broker_server,
            'internal_account_id': str(account.id),
        }
        return connector_class(credentials)

    if platform_upper in ("CTRADER", "CTRADER"):  # normalize cTrader
        try:
            ct_acc = await CTraderAccount.objects.aget(account=account)
        except CTraderAccount.DoesNotExist as e:
            raise ValueError("No linked cTrader account found.") from e
        credentials = {
            'account_id': ct_acc.ctid_trader_account_id,
            'access_token': ct_acc.access_token,
            'refresh_token': ct_acc.refresh_token,
            'is_sandbox': ct_acc.is_sandbox,
            'ctid_user_id': ct_acc.ctid_user_id,
            'internal_account_id': str(account.id),
        }
        return connector_class(credentials)

    supported_platforms = _registry.get_supported_platforms()
    raise ValueError(
        f"Unsupported platform: {platform}. Supported platforms: {supported_platforms}"
    )


def get_supported_platforms() -> list:
    """Get list of all supported trading platforms"""
    return _registry.get_supported_platforms()


def is_platform_supported(platform: str) -> bool:
    """Check if a platform is supported"""
    try:
        _registry.get_connector_class(platform)
        return True
    except ValueError:
        return False


# Legacy compatibility function - can be removed after migration
def get_legacy_connector(account: Account):
    """
    DEPRECATED: Legacy connector factory for backward compatibility.
    Use get_connector() instead for new code.
    """
    import warnings
    warnings.warn(
        "get_legacy_connector is deprecated. Use get_connector() instead.",
        DeprecationWarning,
        stacklevel=2
    )
    
    platform = (account.platform or "").strip()

    if platform.upper() == "MT5":
        from trading_platform.mt5_api_client import MT5APIClient
        mt5_acc = get_object_or_404(MT5Account, account=account)
        return MT5APIClient(
            base_url=settings.MT5_API_BASE_URL,
            account_id=mt5_acc.account_number,
            password=mt5_acc.encrypted_password,
            broker_server=mt5_acc.broker_server,
            internal_account_id=str(account.id),
        )

    if platform.lower() == "ctrader" or platform == "cTrader":
        from connectors.ctrader_client import CTraderClient
        ct_acc = get_object_or_404(CTraderAccount, account=account)
        return CTraderClient(ct_acc)

    raise RuntimeError(f"Unsupported platform: {platform}")
