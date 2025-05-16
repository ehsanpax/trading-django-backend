import MetaTrader5 as mt5
from django.core.management.base import BaseCommand, CommandError
from accounts.models import MT5Account
from mt5.services import MT5Connector
from datetime import datetime, timedelta, timezone

class Command(BaseCommand):
    help = 'Query MT5 for historical deals for a given account and optional order or position identifier.'

    def add_arguments(self, parser):
        parser.add_argument(
            'mt5_login_id',
            type=int,
            help='The MT5 login ID (account_number).'
        )
        parser.add_argument(
            '--identifier',
            type=int,
            default=None,
            help='Optional: Order ticket or Position ID to filter deals by.'
        )
        parser.add_argument(
            '--identifier_type',
            type=str,
            choices=['order', 'position'],
            default=None,
            help="Specify whether --identifier is an 'order' or a 'position'."
        )
        parser.add_argument(
            '--days',
            type=int,
            default=7,
            help='How many days of history to fetch (default: 7).'
        )

    def handle(self, *args, **options):
        mt5_login_id    = options['mt5_login_id']
        identifier      = options['identifier']
        identifier_type = options['identifier_type']
        days_history    = options['days']

        # Validate flag combinations
        if identifier and not identifier_type:
            raise CommandError("--identifier requires --identifier_type ('order' or 'position').")
        if identifier_type and not identifier:
            self.stdout.write(self.style.WARNING(
                "--identifier_type provided without --identifier; ignoring identifier_type."
            ))
            identifier_type = None

        # Fetch the MT5Account record
        try:
            mt5_account = MT5Account.objects.get(account_number=mt5_login_id)
        except MT5Account.DoesNotExist:
            raise CommandError(f"MT5Account with account_number={mt5_login_id} not found.")

        # Initialize the MT5 terminal
        terminal_path = rf"C:\MetaTrader 5\{mt5_login_id}\terminal64.exe"
        if not mt5.initialize(path=terminal_path):
            err = mt5.last_error()
            raise CommandError(f"MT5 initialization failed: {err}")

        # Connect / log in
        connector = MT5Connector(
            account_id=mt5_account.account_number,
            broker_server=mt5_account.broker_server
        )
        login_res = connector.connect(password=mt5_account.encrypted_password)
        if 'error' in login_res:
            raise CommandError(f"MT5 login failed: {login_res['error']}")
        self.stdout.write(self.style.SUCCESS("Connected to MT5."))

        # Choose the appropriate API overload
        if identifier and identifier_type == 'order':
            self.stdout.write(f"Fetching deals for order ticket {identifier}")
            deals = mt5.history_deals_get(order=identifier)
        elif identifier and identifier_type == 'position':
            self.stdout.write(f"Fetching deals for position ID {identifier}")
            deals = mt5.history_deals_get(position=identifier)
        else:
            # Use date-range overload with a 10-hour padding on the upper bound
            utc_now  = datetime.now(timezone.utc)
            utc_from = utc_now - timedelta(days=days_history)
            utc_to   = utc_now + timedelta(hours=10)  # pad upper bound by 10 hours
            self.stdout.write(
                f"Fetching all deals from {utc_from.isoformat()} to {utc_to.isoformat()} (UTC with padding)"
            )
            deals = mt5.history_deals_get(utc_from, utc_to)

        # Error handling
        if deals is None:
            code, msg = mt5.last_error()
            raise CommandError(f"history_deals_get failed: {code} – {msg}")

        # Manual filter fallback if needed
        if identifier and identifier_type and isinstance(deals, (list, tuple)):
            if identifier_type == 'order':
                deals = [d for d in deals if d.order == identifier]
            else:
                deals = [d for d in deals if d.position_id == identifier]

        # Output results
        if not deals:
            self.stdout.write(self.style.WARNING("No deals found."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Found {len(deals)} deal(s):"))
            for idx, deal in enumerate(deals, start=1):
                time_str = datetime.fromtimestamp(deal.time, timezone.utc).isoformat()
                self.stdout.write(f"\n--- Deal {idx} ---")
                for field in (
                    'ticket', 'order', 'position_id', 'symbol',
                    'volume', 'price', 'profit', 'commission', 'swap', 'reason'
                ):
                    self.stdout.write(f"  {field}: {getattr(deal, field)}")

        # Disconnect
        if mt5.terminal_info():
            mt5.shutdown()
            self.stdout.write("MT5 connection closed.")
