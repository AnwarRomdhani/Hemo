import logging
from rest_framework.permissions import BasePermission
from centers.models import AdministrativeStaff, MedicalStaff, ParamedicalStaff, TechnicalStaff, WorkerStaff, UserProfile

logger = logging.getLogger(__name__)

class RoleBasedPermission(BasePermission):
    def has_permission(self, request, view):
        user = request.user.username if request.user else 'Anonymous'
        logger.debug("START Permission check: path=%s, method=%s, user=%s, is_authenticated=%s, is_superuser=%s",
                     request.path, request.method, user,
                     request.user.is_authenticated if request.user else False,
                     request.user.is_superuser if request.user else False)

        if request.user and request.user.is_authenticated and request.user.is_superuser:
            logger.info("GRANTED: Superuser %s access to %s %s", user, request.method, request.path)
            return True
        logger.debug("CHECK: User %s is not superuser, proceeding with standard checks", user)

        if not request.user or not request.user.is_authenticated:
            logger.warning("DENIED: Unauthenticated access attempt to %s by %s", request.path, user)
            return False
        logger.debug("CHECK: User %s is authenticated", user)

        tenant = getattr(request, 'tenant', None)
        if not tenant:
            logger.error("DENIED: No tenant found for request to %s by user %s", request.path, user)
            return False
        logger.debug("CHECK: Tenant resolved: %s (ID=%s)", tenant.label, tenant.id)

        try:
            user_profile = UserProfile.objects.get(user=request.user)
            if not user_profile.has_role_privileges():
                logger.warning("DENIED: User %s lacks role privileges (is_verified=%s, admin_accord=%s)",
                              user, user_profile.is_verified, user_profile.admin_accord)
                return False
            logger.debug("CHECK: UserProfile found for %s: is_verified=%s, admin_accord=%s",
                        user, user_profile.is_verified, user_profile.admin_accord)
        except UserProfile.DoesNotExist:
            logger.error("DENIED: No UserProfile found for user %s", user)
            return False

        role = None
        user_center = None
        staff_models = [AdministrativeStaff, MedicalStaff, ParamedicalStaff, TechnicalStaff, WorkerStaff]

        for model in staff_models:
            try:
                staff = model.objects.get(user=request.user)
                role = staff.role
                user_center = staff.center
                logger.debug("CHECK: Found %s for user %s: role=%s, center=%s (ID=%s)",
                            model.__name__, user, role, user_center.label, user_center.id)
                break
            except model.DoesNotExist:
                logger.debug("CHECK: No %s found for user %s", model.__name__, user)
                continue

        if not role or not user_center:
            logger.error("DENIED: User %s has no assigned role or center", user)
            return False

        if user_center.id != tenant.id:
            logger.warning("DENIED: User %s attempted cross-center access (user_center=%s, ID=%s, tenant=%s, ID=%s)",
                          user, user_center.label, user_center.id, tenant.label, tenant.id)
            return False
        logger.debug("CHECK: Tenant matches user center: %s (ID=%s)", tenant.label, tenant.id)

        allowed_roles = getattr(view, 'allowed_roles', [])
        read_only_roles = getattr(view, 'read_only_roles', [])

        logger.debug("CHECK: Permissions for user %s (role=%s) on %s %s. Allowed roles=%s, Read-only roles=%s",
                     user, role, request.method, request.path, allowed_roles, read_only_roles)

        if role == 'LOCAL_ADMIN':
            logger.info("GRANTED: User %s (LOCAL_ADMIN) access to %s %s", user, request.method, request.path)
            return True

        if request.method in ['GET', 'HEAD', 'OPTIONS'] and role in read_only_roles:
            logger.info("GRANTED: User %s (role=%s) read-only access to %s %s",
                       user, role, request.method, request.path)
            return True

        if role in allowed_roles:
            logger.info("GRANTED: User %s (role=%s) access to %s %s", user, role, request.method, request.path)
            return True

        logger.warning("DENIED: Unauthorized access attempt by user %s (role=%s) to %s %s",
                      user, role, request.method, request.path)
        return False