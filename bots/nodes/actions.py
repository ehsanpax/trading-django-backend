from core.interfaces import ActionInterface

class EnterLong(ActionInterface):
    VERSION = 1
    PARAMS_SCHEMA = {}

    def execute(self, strategy):
        strategy.buy()

class EnterShort(ActionInterface):
    VERSION = 1
    PARAMS_SCHEMA = {}

    def execute(self, strategy):
        strategy.sell()

class ExitPosition(ActionInterface):
    VERSION = 1
    PARAMS_SCHEMA = {}

    def execute(self, strategy):
        strategy.close()
