import logging
from django.conf import settings
from accounts.models import Account
from trading_platform.mt5_api_client import MT5APIClient

logger = logging.getLogger(__name__)

class ControlService:
    def __init__(self, instance_id):
        self.instance_id = instance_id
        self.account = self._get_account()

    def _get_account(self):
        try:
            return Account.objects.get(pk=self.instance_id)
        except Account.DoesNotExist:
            return None

    def shutdown(self):
        logger.info(f"ControlService: Shutdown called for account {self.instance_id}")
        if not self.account:
            logger.error(f"ControlService: Account not found for id {self.instance_id}")
            return {"status": "error", "message": "Account not found"}

        logger.info(f"ControlService: Account platform is {self.account.platform}")
        if self.account.platform.lower() == "mt5":
            logger.info("ControlService: Initializing MT5APIClient")
            client = MT5APIClient(base_url=settings.MT5_API_BASE_URL, account_id=self.account.mt5_account.account_number, password=self.account.mt5_account.encrypted_password, broker_server=self.account.mt5_account.broker_server, internal_account_id=str(self.account.id))
            logger.info("ControlService: Calling close_instance on MT5APIClient")
            response = client.close_instance(str(self.account.id))
            logger.info(f"ControlService: Response from close_instance: {response}")
            return response
        else:
            logger.warning(f"ControlService: Platform not supported for account {self.instance_id}")
            return {"status": "error", "message": "Platform not supported"}
