from django.urls import path
from .views import add_center, center_detail, add_staff,generate_report,export_pdf

urlpatterns = [
    path('add-center/', add_center, name='add_center'),  # URL for adding a new Center (root domain)
    path('', center_detail, name='center_detail'),  # Default route for subdomains
    path('add-staff/', add_staff, name='add_staff'),  # URL for adding staff (subdomain)
    path('report/', generate_report, name='generate_report'),
    path('export-pdf/', export_pdf, name='export_pdf'),
]