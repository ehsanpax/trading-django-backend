from tvDatafeed import TvDatafeed

# auto_login=False will pop open a browser window
# — use the Google SSO button to log in,
# then return to the terminal and press ENTER to finish.
tv = TvDatafeed(auto_login=False)
print("✅ TradingView login successful — cookies cached!")
