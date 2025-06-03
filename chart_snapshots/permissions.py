from rest_framework import permissions

class IsOwnerOrAdminOrReadOnlyIfGlobal(permissions.BasePermission):
    """
    Custom permission to only allow owners of an object or admins to edit it.
    Allows read access to global objects for any authenticated user.
    """

    def has_object_permission(self, request, view, obj):
        # Read permissions are allowed for any request,
        # so we'll always allow GET, HEAD or OPTIONS requests.
        if request.method in permissions.SAFE_METHODS:
            # If the object is global, any authenticated user can read it.
            # If it's not global, only the owner can read it (this is handled by get_queryset).
            # This check here is more for detail view.
            return obj.is_global or obj.user == request.user

        # Write permissions.
        # Only the owner of the config can modify/delete it.
        # Or, if it's a global config, admins can also modify/delete it.
        if obj.user == request.user:
            return True
        
        if obj.is_global and request.user.is_staff:
            return True
            
        return False

class CanSetGlobalFlagPermission(permissions.BasePermission):
    """
    Permission to check if a user can set the is_global flag.
    For now, allows any authenticated user to set it on create/update.
    Could be restricted to admins later if needed.
    """
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        # For object-level permission (e.g. on update),
        # allow if user is owner or admin (if it's already global).
        # If user is making their own private config global, that's fine.
        if obj.user == request.user:
            return True
        if obj.is_global and request.user.is_staff: # Admin can change global status of global config
            return True
        return False
