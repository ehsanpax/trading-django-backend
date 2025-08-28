from django.urls import reverse
from rest_framework.test import APITestCase, APIClient
from django.contrib.auth import get_user_model
from accounts.models import Profile, Account


class MyProfileAPITests(APITestCase):
	def setUp(self):
		User = get_user_model()
		self.user = User.objects.create_user(
			username="alice", email="alice@example.com", password="testpass"
		)
		self.client = APIClient()
		self.client.force_authenticate(self.user)

	def test_get_profile_auto_created(self):
		url = reverse('my-profile')
		resp = self.client.get(url)
		self.assertEqual(resp.status_code, 200)
		self.assertIn('timezone', resp.data)

	def test_update_profile_and_default_account_validation(self):
		# Create two accounts: one owned, one not
		my_acc = Account.objects.create(user=self.user, name='A', platform='MT5')
		other_user = get_user_model().objects.create_user('bob', 'bob@example.com', 'pass')
		other_acc = Account.objects.create(user=other_user, name='B', platform='MT5')

		url = reverse('my-profile')
		# Valid update with owned account
		payload = {
			'default_account': my_acc.id,
			'profile_currency': 'USD',
			'timezone': 'UTC',
		}
		resp = self.client.patch(url, payload, format='json')
		self.assertEqual(resp.status_code, 200)
		self.assertEqual(resp.data['default_account'], my_acc.id)

		# Invalid update with someone else's account
		resp2 = self.client.patch(url, {'default_account': other_acc.id}, format='json')
		self.assertEqual(resp2.status_code, 400)
		self.assertIn('default_account', resp2.data)

	def test_currency_and_timezone_validation(self):
		url = reverse('my-profile')
		bad = {'profile_currency': 'USDT', 'timezone': 'Moon/Base-1'}
		resp = self.client.patch(url, bad, format='json')
		self.assertEqual(resp.status_code, 400)
		self.assertIn('profile_currency', resp.data)
		self.assertIn('timezone', resp.data)

	def test_get_profile(self):
		self.client.force_authenticate(self.user)
		url = reverse('my-profile')
		resp = self.client.get(url)
		self.assertEqual(resp.status_code, 200)
		self.assertIn('email', resp.data)
		self.assertEqual(resp.data['email'], 'alice@example.com')

	def test_update_profile_and_user_fields(self):
		self.client.force_authenticate(self.user)
		url = reverse('my-profile')
		payload = {
			'name': 'Alice',
			'surname': 'Trader',
			'phone': '+12025550123',
			'country': 'US',
			'state': 'CA',
			'address': '123 Market St',
			'timezone': 'America/Los_Angeles',
			'profile_currency': 'usd',
			'email': 'newalice@example.com',
			'trading_experience': 'INTERMEDIATE'
		}
		resp = self.client.patch(url, payload, format='json')
		self.assertEqual(resp.status_code, 200)
		self.assertEqual(resp.data['name'], 'Alice')
		self.assertEqual(resp.data['surname'], 'Trader')
		self.assertEqual(resp.data['profile_currency'], 'USD')
		# Verify underlying user updated
		self.user.refresh_from_db()
		self.assertEqual(self.user.email, 'newalice@example.com')
