from rest_framework import generics, permissions
from .models import Account
from .serializers import AccountSerializer

# List all accounts for the authenticated user and create new ones.
class AccountListCreateView(generics.ListCreateAPIView):
    serializer_class = AccountSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Account.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        # ✅ Automatically assign the logged-in user
        serializer.save(user=self.request.user)


# Retrieve, update, or delete a specific account.
class AccountDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = AccountSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'id'

    def get_queryset(self):
        # Ensure users can only access their own accounts.
        return Account.objects.filter(user=self.request.user)
