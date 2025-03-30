"""urls for accounts"""

from django.urls import path
from .views import CreateAccountView
from .views import ListAccountsView
from .views import UpdateAccountView
from .views import DeleteAccountView
from .views import FetchAccountDetailsView

urlpatterns = [
    path("create/", CreateAccountView.as_view(), name="create-account"),
    path("", ListAccountsView.as_view(), name="list-accounts"),
    path("update/<uuid:account_id>/", UpdateAccountView.as_view(), name="update-account"),
    path("delete/<uuid:account_id>/", DeleteAccountView.as_view(), name="delete-account"),
    path("details/<uuid:account_id>/", FetchAccountDetailsView.as_view(), name="fetch-account-details"),
    # You can add additional endpoints (list, detail, update, delete) here.
]
