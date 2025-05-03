# urls.py (updated)
from django.urls import path
from .views import (add_center, center_detail, 
                   add_technical_staff, add_medical_staff, add_paramedical_staff,
                   generate_report, export_pdf,load_delegations,add_machine)

urlpatterns = [
    path('add-center/', add_center, name='add_center'),
    path('', center_detail, name='center_detail'),
    path('add-technical-staff/', add_technical_staff, name='add_technical_staff'),
    path('add-medical-staff/', add_medical_staff, name='add_medical_staff'),
    path('add-paramedical-staff/', add_paramedical_staff, name='add_paramedical_staff'),
    path('report/', generate_report, name='generate_report'),
    path('export-pdf/', export_pdf, name='export_pdf'),
    path('ajax/load-delegations/', load_delegations, name='load_delegations'),
    path('add_machine/', add_machine, name='add_machine'),
]