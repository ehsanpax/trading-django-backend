from decimal import Decimal
from django.utils import timezone
from django.test import TestCase
from django.contrib.auth import get_user_model
from unittest.mock import patch

from accounts.models import Account
from trading.models import Trade
from risk.models import RiskManagement
from risk.management import has_exceeded_daily_loss

class RiskManagementTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='testuser', password='testpass')
        self.account = Account.objects.create(
            user=self.user,
            name="Test Account",
            platform="MT5",
            balance=Decimal("10000.00"),
            equity=Decimal("10000.00")
        )
        self.risk_settings = RiskManagement.objects.create(
            account=self.account,
            max_daily_loss=Decimal("100.00"),
            max_trade_risk=Decimal("1.0"),
            max_open_positions=3,
            enforce_cooldowns=True,
            consecutive_loss_limit=3,
            cooldown_period=timezone.timedelta(minutes=30),
            max_lot_size=Decimal("2.0"),
            max_open_trades_same_symbol=1
        )

    @patch('risk.management.get_total_open_pnl')
    def test_has_exceeded_daily_loss_including_open_trades(self, mock_get_total_open_pnl):
        now = timezone.now()
        # Create a closed trade with -20 loss.
        Trade.objects.create(
            account=self.account,
            instrument="EURUSD",
            direction="BUY",
            lot_size=Decimal("1.0"),
            remaining_size=Decimal("1.0"),
            entry_price=Decimal("1.2000"),
            stop_loss=Decimal("1.1900"),
            profit_target=Decimal("1.2100"),
            risk_percent=Decimal("0.5"),
            projected_profit=Decimal("100.00"),
            projected_loss=Decimal("100.00"),
            actual_profit_loss=Decimal("-20.00"),
            trade_status="closed",
            closed_at=now
        )
        # Patch open P&L to simulate open trades with -90 loss.
        mock_get_total_open_pnl.return_value = Decimal("-90.00")
        self.assertTrue(has_exceeded_daily_loss(self.risk_settings))
