from django.core.exceptions import ObjectDoesNotExist
from .models import Center

class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Extract the subdomain from the host
        host = request.META['HTTP_HOST'].split('.')
        subdomain = host[0] if len(host) > 1 else None

        if subdomain:
            try:
                # Set the current tenant in the request object
                request.tenant = Center.objects.get(sub_domain=subdomain)
            except ObjectDoesNotExist:
                request.tenant = None  # No tenant found for this subdomain
        else:
            request.tenant = None  # No subdomain (root domain)

        response = self.get_response(request)
        return response