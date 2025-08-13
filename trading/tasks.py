from celery import shared_task
from accounts.models import Account
from .services import calculate_account_drawdown

@shared_task
def update_account_drawdowns():
    """
    Celery task to update the maximum drawdown for all accounts.
    """
    accounts = Account.objects.all()
    for account in accounts:
        calculate_account_drawdown(account)
