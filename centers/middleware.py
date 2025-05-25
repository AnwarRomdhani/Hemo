# centers/middleware.py
from django.core.exceptions import ObjectDoesNotExist
from django.http import Http404
from .models import Center

class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Skip if it's the admin interface
        if request.path.startswith('/admin/'):
            return self.get_response(request)
            
        # Extract the subdomain from the host
        host = request.META['HTTP_HOST'].split(':')[0]
        subdomain = host.split('.')[0] if len(host.split('.')) > 1 else None

        # Handle localhost case (root domain)
        if subdomain in ['localhost', '127.0.0.1']:
            request.tenant = None
            return self.get_response(request)

        if subdomain:
            try:
                request.tenant = Center.objects.get(sub_domain=subdomain)
            except ObjectDoesNotExist:
                raise Http404("Center not found for this subdomain")
        else:
            request.tenant = None

        response = self.get_response(request)
        return response
    
