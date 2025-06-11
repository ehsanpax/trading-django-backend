from dataclasses import dataclass
from typing import List

@dataclass
class BotParameter:
    name: str
    parameter_type: str
    default_value: any
    value: any
    value_from: str
    value_to: str

class Filters:

    def run():
        return True


class BaseBot:
    parameters: List[BotParameter] = []
    Direction = bia


    def setup()
        pass

    def run():
        pass



class NewBot(BaseBot):
    parameters = [
        BotParameter(
            name="rsi"
        )
    ]

    def 






NewBot.parameters




