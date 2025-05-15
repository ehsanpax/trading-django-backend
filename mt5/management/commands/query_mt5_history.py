import MetaTrader5 as mt5
from django.core.management.base import BaseCommand, CommandError
from accounts.models import MT5Account
from mt5.services import MT5Connector # Assuming your MT5Connector is here
from datetime import datetime, timedelta, timezone

class Command(BaseCommand):
    help = 'Queries MT5 for historical deals for a given account and identifier (order or position).'

    def add_arguments(self, parser):
        parser.add_argument('mt5_login_id', type=int, help='The MT5 login ID (account_number).')
        parser.add_argument('--identifier', type=int, help='Optional: The Order ID or Position ID to query for.', nargs='?', default=None)
        parser.add_argument(
            '--identifier_type',
            type=str,
            choices=['order', 'position'],
            help="Specify whether the identifier is an 'order' or a 'position'. Required if --identifier is provided.",
            nargs='?',
            default=None
        )
        parser.add_argument(
            '--days',
            type=int,
            default=7,
            help='How many days of history to fetch (default: 7 days).'
        )

    def handle(self, *args, **options):
        mt5_login_id = options['mt5_login_id']
        identifier = options['identifier']
        identifier_type = options['identifier_type']
        days_history = options['days']

        if identifier and not identifier_type:
            raise CommandError("If --identifier is provided, --identifier_type ('order' or 'position') must also be provided.")
        if not identifier and identifier_type:
            self.stdout.write(self.style.WARNING("--identifier_type provided without --identifier. Will fetch all deals for the period."))
            identifier_type = None # Ignore if no identifier

        if identifier and identifier_type:
            self.stdout.write(f"Attempting to query history for MT5 Account: {mt5_login_id}, {identifier_type.capitalize()} ID: {identifier}, Days: {days_history}")
        else:
            self.stdout.write(f"Attempting to query all deal history for MT5 Account: {mt5_login_id}, Days: {days_history}")

        try:
            mt5_account = MT5Account.objects.get(account_number=mt5_login_id)
        except MT5Account.DoesNotExist:
            raise CommandError(f"MT5Account with account_number {mt5_login_id} not found in the database.")

        connector = None
        try:
            self.stdout.write(f"Initializing MT5Connector for account {mt5_account.account_number} on server {mt5_account.broker_server}...")
            # Ensure MT5 is initialized for this specific command run if not already
            if not mt5.initialize(path=rf"C:\MetaTrader 5\{mt5_account.account_number}\terminal64.exe"):
                 init_error = mt5.last_error()
                 self.stderr.write(self.style.ERROR(f"MT5 Initialization Failed. Error: {init_error}"))
                 # Attempt to proceed, connect() might also try to initialize
            
            connector = MT5Connector(
                account_id=mt5_account.account_number,
                broker_server=mt5_account.broker_server
            )
            
            self.stdout.write("Attempting to connect to MT5...")
            login_result = connector.connect(password=mt5_account.encrypted_password)

            if "error" in login_result:
                raise CommandError(f"MT5 connection failed: {login_result['error']}")
            
            self.stdout.write(self.style.SUCCESS("Successfully connected to MT5."))

            # Use UTC now for the query window. The `days` parameter controls the lookback.
            utc_to = datetime.now(timezone.utc)
            utc_from = utc_to - timedelta(days=days_history) # Default is 7 days, adjustable by --days
            
            self.stdout.write(f"DEBUG: Querying history deals from {utc_from.isoformat()} to {utc_to.isoformat()} (UTC window)")

            deals = None
            if identifier and identifier_type == 'order':
                self.stdout.write(f"Fetching history deals by order_id: {identifier}")
                deals = mt5.history_deals_get(utc_from, utc_to, order=identifier)
            elif identifier and identifier_type == 'position':
                self.stdout.write(f"Fetching history deals by position_id: {identifier}")
                deals = mt5.history_deals_get(utc_from, utc_to, position=identifier)
            else: # Fetch all deals for the period
                self.stdout.write(f"Fetching all history deals")
                deals = mt5.history_deals_get(utc_from, utc_to)

            if deals is None:
                err_code, err_msg = mt5.last_error()
                self.stderr.write(self.style.ERROR(f"mt5.history_deals_get() call failed: {err_code} - {err_msg}"))
                return

            if not deals: # Deals is an empty tuple or list
                if identifier and identifier_type:
                    self.stdout.write(self.style.WARNING(f"No deals found for {identifier_type} ID {identifier} in the last {days_history} days."))
                else:
                    self.stdout.write(self.style.WARNING(f"No deals found for any identifier in the last {days_history} days."))
                return
            
            if identifier and identifier_type:
                self.stdout.write(self.style.SUCCESS(f"Found {len(deals)} deal(s) for {identifier_type} ID {identifier}:"))
            else:
                self.stdout.write(self.style.SUCCESS(f"Found {len(deals)} total deal(s):"))
            for i, deal in enumerate(deals):
                self.stdout.write(f"\n--- Deal {i+1} ---")
                deal_dict = {
                    "ticket": deal.ticket,
                    "order": deal.order,
                    "time": datetime.fromtimestamp(deal.time, tz=timezone.utc).isoformat(),
                    "time_msc": deal.time_msc,
                    "type": deal.type, # DEAL_TYPE_BUY, DEAL_TYPE_SELL
                    "entry": deal.entry, # DEAL_ENTRY_IN, DEAL_ENTRY_OUT, DEAL_ENTRY_INOUT
                    "magic": deal.magic,
                    "reason": deal.reason, # DEAL_REASON_CLIENT, DEAL_REASON_SL, DEAL_REASON_TP, etc.
                    "position_id": deal.position_id,
                    "volume": deal.volume,
                    "price": deal.price,
                    "commission": deal.commission,
                    "swap": deal.swap,
                    "profit": deal.profit,
                    "fee": deal.fee,
                    "symbol": deal.symbol,
                    "comment": deal.comment,
                    "external_id": deal.external_id,
                }
                for key, value in deal_dict.items():
                    self.stdout.write(f"  {key}: {value}")
            
            self.stdout.write(self.style.SUCCESS("\nFinished querying history."))

        except Exception as e:
            self.stderr.write(self.style.ERROR(f"An unexpected error occurred: {e}"))
            import traceback
            self.stderr.write(traceback.format_exc())
        finally:
            if mt5.terminal_info(): # Check if MT5 was initialized
                self.stdout.write("Shutting down MT5 connection for command.")
                mt5.shutdown()
