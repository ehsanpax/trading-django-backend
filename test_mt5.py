import time
import MetaTrader5 as mt5

if not mt5.initialize():
    print("Initialization failed:", mt5.last_error())
    exit(1)
print("MT5 Initialized.")

account_id = 13527698  # Your account ID
password = "fhcFA22##"
server = "FundedNext-Server 2"

print(f"Attempting login for account {account_id} on {server}...")
if not mt5.login(account_id, password, server):
    error_code, error_message = mt5.last_error()
    print(f"Login failed: {error_code} - {error_message}")
else:
    print("Login successful! Account info:", mt5.account_info())
    time.sleep(5)
    print("After 5 seconds, account info:", mt5.account_info())

mt5.shutdown()
