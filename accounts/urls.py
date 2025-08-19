"""urls for accounts"""

from django.urls import path
from .views import CreateAccountView
from .views import ListAccountsView
from .views import UpdateAccountView
from .views import DeleteAccountView
from .views import FetchAccountDetailsView
from .views import ProfitTakingProfileViewSet
from .views import MeView, UserRegistrationView # Added MeView import
from .views import InternalCTraderTokensView # Added InternalCTraderTokensView import

# bind the viewset actions to view functions
profit_profile_list = ProfitTakingProfileViewSet.as_view({
    'get': 'list',
    'post': 'create',
})
profit_profile_detail = ProfitTakingProfileViewSet.as_view({
    'get': 'retrieve',
    'put': 'update',
    'patch': 'partial_update',
    'delete': 'destroy',
})

urlpatterns = [
    path("register/", UserRegistrationView.as_view(), name="register"),
    path("create/", CreateAccountView.as_view(), name="create-account"),
    path("", ListAccountsView.as_view(), name="list-accounts"),
    path("update/<uuid:account_id>/", UpdateAccountView.as_view(), name="update-account"),
    path("delete/<uuid:account_id>/", DeleteAccountView.as_view(), name="delete-account"),
    path("details/<uuid:account_id>/", FetchAccountDetailsView.as_view(), name="fetch-account-details"),
    path('profit-profiles/', profit_profile_list, name='profit-profile-list'),
    path('profit-profiles/<int:pk>/', profit_profile_detail, name='profit-profile-detail'),
    path('me/', MeView.as_view(), name='me'), # Added 'me' endpoint
    # Internal endpoints for microservice (accept int CTraderAccount.id or UUID Account.id)
    path("internal/brokers/ctrader/<str:ctrader_account_id>/tokens", InternalCTraderTokensView.as_view(), name="internal-ctrader-tokens"),
    
    # You can add additional endpoints (list, detail, update, delete) here.
]
