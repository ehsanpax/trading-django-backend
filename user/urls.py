from django.urls import path
from .views import UserStudioLayoutListCreateAPIView, UserStudioLayoutRetrieveUpdateDestroyAPIView, CreateUserToken

urlpatterns = [
    path('user-studio-layouts/', UserStudioLayoutListCreateAPIView.as_view(), name='user-studio-layout-list-create'),
    path('user-studio-layouts/<int:id>/', UserStudioLayoutRetrieveUpdateDestroyAPIView.as_view(), name='user-studio-layout-retrieve-update-destroy'),
        path("create-token/", CreateUserToken.as_view(), name="create_user_token"),
]
