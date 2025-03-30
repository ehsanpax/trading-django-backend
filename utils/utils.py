from functools import wraps
from django.http import JsonResponse
from rest_framework.authtoken.models import Token

def token_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        print(4545454)
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        print(2222, auth_header)
        if auth_header.startswith('Token '):
            token_key = auth_header.split(' ')[1]
            try:
                print(1111111, token_key)
                token = Token.objects.get(key=token_key)
                request.user = token.user  # set the user on the request
            except Token.DoesNotExist:
                return JsonResponse({'detail': 'Invalid token.'}, status=403)
        else:
            return JsonResponse({'detail': 'Authentication credentials were not provided.'}, status=403)
        return view_func(request, *args, **kwargs)
    return _wrapped_view
