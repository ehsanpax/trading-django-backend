# This will ensure that strategy and indicator modules are loaded
# when the Django app starts, populating their respective registries.
import bots.strategy_templates.ema_crossover_v1
import indicators.ema
import indicators.atr
