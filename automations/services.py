# services.py
"""Round‑robin account selection limited to the `automation_user`."""
from django.contrib.auth import get_user_model
from accounts.models import Account
from .models import RoundRobinPointer


def select_next_account():
    """Return the next active Account belonging to the special `automation_user`.

    • Filters `Account` objects where `active=True` and `user.username == 'automation_user'`.
    • Uses a single‑row `RoundRobinPointer` (id=1) to remember the last account used.
    """
    User = get_user_model()
    try:
        automation_user = User.objects.get(username='automation_user')
    except User.DoesNotExist:
        return None

    accounts = list(
        Account.objects.filter(active=True, user=automation_user)
    )
    if not accounts:
        return None

    ptr, _ = RoundRobinPointer.objects.get_or_create(id=1)

    if ptr.last_used in accounts:
        next_idx = (accounts.index(ptr.last_used) + 1) % len(accounts)
    else:
        next_idx = 0

    selected = accounts[next_idx]
    ptr.last_used = selected
    ptr.save(update_fields=["last_used"])
    return selected