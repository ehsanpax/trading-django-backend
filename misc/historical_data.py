import pandas as pd
from datetime import datetime, timezone, timedelta
import oandapyV20
from oandapyV20 import API
from oandapyV20.endpoints.instruments import InstrumentsCandles

ACCESS_TOKEN = "8617505e3109641a4bc8b10bcbf546ed-d1a4b2273a700dcbc4840439c9701e42"
api = API(access_token=ACCESS_TOKEN, environment="practice")

INSTRUMENT  = "EUR_AUD"
GRANULARITY = "M1"
START_DT    = datetime(2019, 1, 1, tzinfo=timezone.utc)
END_DT      = datetime.now(timezone.utc)

all_dfs = []
current = START_DT
BAR_DELTA = timedelta(minutes=1)
BATCH     = 5000

while current < END_DT:
    params = {
        "from":        current.isoformat(),
        "granularity": GRANULARITY,
        "count":       BATCH
    }
    r    = InstrumentsCandles(instrument=INSTRUMENT, params=params)
    resp = api.request(r)
    candles = resp.get("candles", [])
    if not candles:
        break

    df = pd.DataFrame([{
        "time":  pd.to_datetime(c["time"]),
        "open":  float(c["mid"]["o"]),
        "high":  float(c["mid"]["h"]),
        "low":   float(c["mid"]["l"]),
        "close": float(c["mid"]["c"]),
        "volume": int(c["volume"])
    } for c in candles]).set_index("time")
    print(f"Fetched {len(candles)} bars from {current.date()} to {df.index.max().date()}")

    all_dfs.append(df)

    # move current to the next bar after the last one we just got
    last_ts = df.index.max()
    current = last_ts + BAR_DELTA

full = pd.concat(all_dfs).sort_index().loc[START_DT:END_DT]
full.to_csv(f"{INSTRUMENT}_{GRANULARITY}_{START_DT.date()}_to_{END_DT.date()}.csv")
print("Bars:", len(full))
