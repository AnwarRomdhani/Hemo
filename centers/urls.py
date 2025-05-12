# urls.py (updated)
from django.urls import path
from .views import (center_detail, 
                   add_technical_staff, add_medical_staff, add_paramedical_staff,
                   generate_report, export_pdf,load_delegations,add_machine,add_patient,add_cnam,
                   list_patients,patient_detail,load_methods,add_disease_ref,add_complication_ref,CenterLoginView
                   )
from django.contrib.auth.views import LoginView, LogoutView

urlpatterns = [
    path('add_patient/', add_patient, name='add_patient'),
    path('', center_detail, name='center_detail'),
    path('add_cnam/',add_cnam, name='add_cnam'),
    path('add-technical-staff/', add_technical_staff, name='add_technical_staff'),
    path('add-medical-staff/', add_medical_staff, name='add_medical_staff'),
    path('add-paramedical-staff/', add_paramedical_staff, name='add_paramedical_staff'),
    path('report/', generate_report, name='generate_report'),
    path('export-pdf/', export_pdf, name='export_pdf'),
    path('ajax/load-delegations/', load_delegations, name='load_delegations'),
    path('add_machine/', add_machine, name='add_machine'),
    path('list_patients/',list_patients,name='list_patients'),
    path('patient/<int:pk>/', patient_detail, name='patient_detail'),
    path('load-methods/', load_methods, name='load_methods'),
    path('add-disease-ref/', add_disease_ref, name='add_disease_ref'),
    path('add-complication-ref/', add_complication_ref, name='add_complication_ref'),
    path('login/', CenterLoginView, name='login'),
    path('logout/', LogoutView.as_view(next_page='login'), name='logout'),
]