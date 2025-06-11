import logging
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from decimal import Decimal

from accounts.models import Account, MT5Account
from trading.models import InstrumentSpecification
from mt5.services import MT5Connector # Assuming MT5Service is the one with get_symbol_info
# If cTrader or other platforms are needed, import their services too.

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Populates the InstrumentSpecification table using data from a trading account for specified symbols.'

    def add_arguments(self, parser):
        parser.add_argument('--account_id', type=str, required=True, help='The UUID of the Account to use for fetching symbol info.')
        parser.add_argument('--symbols', type=str, required=True, help='Comma-separated list of instrument symbols (e.g., EURUSD,XAUUSD).')
        # parser.add_argument('--platform', type=str, choices=['MT5', 'CTRADER'], help='Specify platform if account has multiple types or for clarity.')

    @transaction.atomic
    def handle(self, *args, **options):
        account_id_str = options['account_id']
        symbols_str = options['symbols']
        symbols_list = [s.strip().upper() for s in symbols_str.split(',')]

        if not symbols_list:
            raise CommandError("No symbols provided.")

        try:
            account = Account.objects.get(id=account_id_str)
        except Account.DoesNotExist:
            raise CommandError(f"Account with ID '{account_id_str}' not found.")

        self.stdout.write(f"Processing account: {account.name} (ID: {account.id}, Platform: {account.platform})")

        if account.platform.upper() == 'MT5':
            try:
                mt5_account_details = MT5Account.objects.get(account=account)
            except MT5Account.DoesNotExist:
                raise CommandError(f"MT5Account details not found for Account ID '{account_id_str}'. Cannot connect.")
            
            # Ensure password is not logged or stored here. This command assumes connection can be made.
            # For a real script, password might need to be fetched securely or script run in an env where MT5 is already connected.
            # The MT5Connector might need to be adapted if it requires password for each call,
            # or if it maintains a session. For symbol_info, it usually needs an active connection.
            # The current MT5Connector in mt5/services.py seems to manage its own connection state.
            # It requires account_id (login) and server for __init__, and password for .connect()
            # This command cannot securely get the password.
            # Assumption: MT5 terminal corresponding to mt5_account_details.account_number is running and logged in,
            # or the MT5Connector can initialize and login if needed (which it tries to do).
            # For this script, we might need a simplified way to get symbol_info if the terminal is already active.
            # The provided MT5Connector's get_symbol_info doesn't explicitly call connect().
            # It relies on mt5.symbol_info() which requires prior initialization.
            
            # Let's assume we need to initialize and connect if not already.
            # This is a simplification; a robust script would handle password securely or expect an active session.
            self.stdout.write(f"Attempting to use MT5 account: {mt5_account_details.account_number} on server {mt5_account_details.broker_server}")
            
            # The MT5Connector in the project seems to manage terminal instances per account_id (which is mt5_account_details.account_number)
            # The MT5Connector's __init__ takes account_id (the login number) and broker_server.
            # Its connect method takes the password.
            # This management command cannot securely access the password.
            # For this script to work, we must assume that an MT5 terminal is already running and initialized
            # for the target account, or that mt5.initialize() can work without a specific terminal path if one is already running.

            # Simplification: Try to initialize globally if no specific terminal path is required by the library for symbol_info
            # after a terminal has been launched manually.
            import MetaTrader5 as mt5
            if not mt5.terminal_info():
                if not mt5.initialize():
                    raise CommandError(f"Failed to initialize MetaTrader 5: {mt5.last_error()}")
                self.stdout.write("MetaTrader 5 initialized globally for script.")
            
            # If a specific account login is needed for symbol_info for that server's symbols:
            # account_info = mt5.account_info()
            # if not account_info or account_info.login != mt5_account_details.account_number:
            #     self.stdout.write(f"MT5 not logged into target account {mt5_account_details.account_number}. Symbol info might be default or fail.")
            #     # This is where login would be needed, but we don't have password.

            for symbol_code in symbols_list:
                self.stdout.write(f"Fetching info for symbol: {symbol_code}...")
                mt5_symbol_info = mt5.symbol_info(symbol_code)

                if not mt5_symbol_info:
                    self.stderr.write(self.style.WARNING(f"Could not retrieve info for symbol: {symbol_code} from MT5."))
                    continue
                
                # Map MT5 SymbolInfo to our InstrumentSpecification fields
                # (Referencing MT5 documentation for field names like 'point', 'trade_contract_size', etc.)
                defaults = {
                    'description': mt5_symbol_info.description,
                    'source_platform': 'MT5',
                    'contract_size': Decimal(str(mt5_symbol_info.trade_contract_size)),
                    'base_currency': mt5_symbol_info.currency_base,
                    'quote_currency': mt5_symbol_info.currency_profit, # Profit currency is usually quote or account currency
                    'margin_currency': mt5_symbol_info.currency_margin,
                    'min_volume': Decimal(str(mt5_symbol_info.volume_min)),
                    'max_volume': Decimal(str(mt5_symbol_info.volume_max)),
                    'volume_step': Decimal(str(mt5_symbol_info.volume_step)),
                    'tick_size': Decimal(str(mt5_symbol_info.point)),
                    'tick_value': Decimal(str(mt5_symbol_info.trade_tick_value)) if hasattr(mt5_symbol_info, 'trade_tick_value') else None,
                    'digits': mt5_symbol_info.digits,
                }
                # Filter out None values from defaults if model fields don't allow null but have blanks
                # Our model allows nulls for most of these, so it's fine.

                spec, created = InstrumentSpecification.objects.update_or_create(
                    symbol=symbol_code,
                    defaults=defaults
                )

                if created:
                    self.stdout.write(self.style.SUCCESS(f"Created InstrumentSpecification for {symbol_code}"))
                else:
                    self.stdout.write(self.style.SUCCESS(f"Updated InstrumentSpecification for {symbol_code}"))
            
            # mt5.shutdown() # Shutdown if we initialized it here.
            # If relying on an already running terminal, don't shut it down.

        elif account.platform.upper() == 'CTRADER':
            # TODO: Implement for cTrader if/when its symbol info service is available
            self.stderr.write(self.style.WARNING(f"cTrader symbol info fetching not yet implemented in this script."))
            pass
        else:
            self.stderr.write(self.style.ERROR(f"Unsupported platform: {account.platform}"))
            return

        self.stdout.write(self.style.SUCCESS("Successfully finished populating instrument specifications."))
