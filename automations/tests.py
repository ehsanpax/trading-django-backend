# tests.py
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase
from django.contrib.auth import get_user_model
from accounts.models import Account
from automations.models import RoundRobinPointer

User = get_user_model()

class ExecuteAITradeTests(APITestCase):
    def setUp(self):
        self.automation_user, _ = User.objects.get_or_create(
            username="automation_user",
            defaults={"email": "auto@example.com"}
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.automation_user)

        self.account1 = Account.objects.create(user=self.automation_user, platform="MT5", active=True)
        self.account2 = Account.objects.create(user=self.automation_user, platform="MT5", active=True)

        RoundRobinPointer.objects.update_or_create(
            id=1,
            defaults={"last_used": self.account2}
        )

    def test_round_robin_account_selection(self):
        url = reverse('ai_trade_execute')
        payload = {
            'symbol': 'EURUSD',
            'direction': 'BUY',
            'entry_price': '1.10000',
            'stop_loss_distance': 50,
            'take_profit': '1.10500',
            'risk_percent': 0.5,
        }
        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, 400)
        print(response.data)  # Debugging line to check the response data
        self.assertIn(str(self.account1.id), response.data.get('message', ''))

