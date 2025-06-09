class BaseProvider:

    def __init__(self, account_info: dict):
        self.account_info = account_info

    def setup():
        pass


    def open_position(**kwargs) -> str:
        return ""

    
class IgProvider(BaseProvider):

    def setup():
        xx


    def open_position(**kwargs) -> str:
        return ""




class Adapter:

    def __init__(self, account_info: dict):
        self.account_info: dict = account_info
        self.provider = self.get_provider()

    def get_provider(self) -> BaseProvider:
        if account_info.get("account_type") == "IG":
            return IgProvider



    def setup(self):
        self.provider.setup()

    def open_position(**kwargs) -> str:
        self.provider.open_position(**kwargs)



account_info = {
    "account_type": "IG"

}
adapter = Adapter(account_info=account_info)

adapter.open_position({})


def view():

    account_info = {
        "account_type": "IG"

    }
    position_info = {
        "size": "dfd"
    }
    adapter = Adapter(account_info=account_info)

    position_id = adapter.open_position(position_info)

