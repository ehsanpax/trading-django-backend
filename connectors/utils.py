# ctrader_app/utils.py
import asyncio

def deferred_to_future(deferred):
    """
    Converts a Twisted Deferred into an asyncio Future.
    Only wraps the object if it has the 'addCallbacks' attribute.
    """
    # If it's already an awaitable (i.e. no 'addCallbacks'), return it directly.
    if not hasattr(deferred, "addCallbacks"):
        return deferred  # assume it's already awaitable

    loop = asyncio.get_event_loop()
    fut = loop.create_future()

    def callback(result):
        if not fut.done():
            fut.set_result(result)

    def errback(err):
        if not fut.done():
            fut.set_exception(err.value)

    deferred.addCallbacks(callback, errback)
    return fut
