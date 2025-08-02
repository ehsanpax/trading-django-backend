from rest_framework.views import exception_handler
from rest_framework.response import Response
import logging

logger = logging.getLogger(__name__)

def custom_exception_handler(exc, context):
    # Call REST framework's default exception handler first,
    # to get the standard error response.
    response = exception_handler(exc, context)

    # Now, customize the response data.
    if response is not None:
        error_payload = {
            "error_code": response.data.get("code", response.status_code),
            "detail": []
        }
        if 'detail' in response.data:
            error_payload["detail"].append({
                "msg": response.data["detail"],
                "type": response.data.get("code", "error")
            })
        response.data = error_payload

    # Log the exception
    logger.error(f"Unhandled exception: {exc}", exc_info=True)

    return response
