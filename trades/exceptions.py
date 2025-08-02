from rest_framework.exceptions import APIException

class BrokerAPIError(APIException):
    """
    Custom exception for errors returned by the broker's API.
    """
    status_code = 503
    default_detail = 'Broker API error.'
    default_code = 'broker_api_error'

class BrokerConnectionError(APIException):
    """
    Custom exception for network-related issues when communicating with the broker.
    """
    status_code = 504
    default_detail = 'Broker connection error.'
    default_code = 'broker_connection_error'

class TradeValidationError(APIException):
    """
    Custom exception for business logic failures, such as invalid trade parameters.
    """
    status_code = 400
    default_detail = 'Trade validation error.'
    default_code = 'trade_validation_error'

class TradeSyncError(APIException):
    """
    Custom exception for critical errors that occur during data synchronization.
    """
    status_code = 500
    default_detail = 'Trade synchronization error.'
    default_code = 'trade_sync_error'
