from .choices import ServiceTypeChoices
from mt5.services import MT5Connector
from connectors.ctrader_connector import CTraderConnector

MAPPING = {
    ServiceTypeChoices.MT5.value: MT5Connector,
    ServiceTypeChoices.CTRADER.value: CTraderConnector
}