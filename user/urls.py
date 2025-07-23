from django.urls import path
from .views import CreateUserToken

urlpatterns = [
    path("create-token/", CreateUserToken.as_view(), name="create_user_token"),
]
