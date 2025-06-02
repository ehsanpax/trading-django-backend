import pandas as pd

# --- Configuration ---
# Replace with the actual path to your CSV file
csv_file_path = 'XAU_USD_M1_2019-01-01_to_2025-04-30.csv' # <<<--- **UPDATE THIS PATH**

# Update these column names if they are different in your CSV file
time_column = 'time' # TradingView often uses 'time' for the timestamp
ohlcv_columns = ['open', 'high', 'low', 'close', 'volume']

# --- Load Data ---
print(f"Loading data from: {csv_file_path}")

try:
    # Read the CSV file
    # parse_dates tells pandas to treat the time_column as dates/times
    # index_col sets the time_column as the DataFrame's index, which is handy for time series
    df = pd.read_csv(
        csv_file_path,
        parse_dates=[time_column],
        index_col=time_column
    )

    # Ensure expected columns exist (optional but good practice)
    if not all(col in df.columns for col in ohlcv_columns):
        print("Error: Not all expected OHLCV columns found in the CSV.")
        print(f"Expected: {ohlcv_columns}")
        print(f"Found: {df.columns.tolist()}")
    else:
        # Keep only the necessary columns if the CSV has others
        df = df[ohlcv_columns]

        # Display the first few rows and data types to verify
        print("\nData loaded successfully.")
        print("\nFirst 5 rows:")
        print(df.head())

        print("\nData Info:")
        df.info()

        print(f"\nTotal number of rows loaded: {len(df)}")


except FileNotFoundError:
    print(f"Error: The file was not found at {csv_file_path}")
except Exception as e:
    print(f"An error occurred during file loading or processing: {e}")