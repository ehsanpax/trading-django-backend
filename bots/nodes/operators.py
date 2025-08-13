from core.interfaces import OperatorInterface

class GreaterThan(OperatorInterface):
    VERSION = 1
    PARAMS_SCHEMA = {}

    def compute(self, a, b) -> bool:
        return a > b

class LessThan(OperatorInterface):
    VERSION = 1
    PARAMS_SCHEMA = {}

    def compute(self, a, b) -> bool:
        return a < b

class EqualTo(OperatorInterface):
    VERSION = 1
    PARAMS_SCHEMA = {}

    def compute(self, a, b) -> bool:
        return a == b

class NotEqualTo(OperatorInterface):
    VERSION = 1
    PARAMS_SCHEMA = {}

    def compute(self, a, b) -> bool:
        return a != b

class GreaterThanOrEqualTo(OperatorInterface):
    VERSION = 1
    PARAMS_SCHEMA = {}

    def compute(self, a, b) -> bool:
        return a >= b

class LessThanOrEqualTo(OperatorInterface):
    VERSION = 1
    PARAMS_SCHEMA = {}

    def compute(self, a, b) -> bool:
        return a <= b

class CrossesAbove(OperatorInterface):
    VERSION = 1
    PARAMS_SCHEMA = {}

    def compute(self, series_a, series_b) -> bool:
        # Simplified for now, assumes series are pandas Series
        return series_a.iloc[-2] < series_b.iloc[-2] and series_a.iloc[-1] > series_b.iloc[-1]

class CrossesBelow(OperatorInterface):
    VERSION = 1
    PARAMS_SCHEMA = {}

    def compute(self, series_a, series_b) -> bool:
        # Simplified for now, assumes series are pandas Series
        return series_a.iloc[-2] > series_b.iloc[-2] and series_a.iloc[-1] < series_b.iloc[-1]

class Crosses(OperatorInterface):
    VERSION = 1
    PARAMS_SCHEMA = {}

    def compute(self, series_a, series_b) -> bool:
        # Simplified for now, assumes series are pandas Series
        return (series_a.iloc[-2] < series_b.iloc[-2] and series_a.iloc[-1] > series_b.iloc[-1]) or \
               (series_a.iloc[-2] > series_b.iloc[-2] and series_a.iloc[-1] < series_b.iloc[-1])

class And(OperatorInterface):
    VERSION = 1
    PARAMS_SCHEMA = {}

    def compute(self, *args) -> bool:
        return all(args)

class Or(OperatorInterface):
    VERSION = 1
    PARAMS_SCHEMA = {}

    def compute(self, *args) -> bool:
        return any(args)

class Not(OperatorInterface):
    VERSION = 1
    PARAMS_SCHEMA = {}

    def compute(self, a) -> bool:
        return not a

class ConstantValue(OperatorInterface):
    VERSION = 1
    PARAMS_SCHEMA = {"value": {"type": "number"}}

    def compute(self, value) -> float:
        return float(value)
