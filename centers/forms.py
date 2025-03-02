from django import forms
from .models import Center, TechnicalStaff, MedicalStaff, ParamedicalStaff

class CenterForm(forms.ModelForm):
    class Meta:
        model = Center
        fields = ['sub_domain', 'tel', 'nom']

class TechnicalStaffForm(forms.ModelForm):
    class Meta:
        model = TechnicalStaff
        fields = ['nom', 'prenom', 'cin', 'qualification']

class MedicalStaffForm(forms.ModelForm):
    class Meta:
        model = MedicalStaff
        fields = ['nom', 'prenom', 'cin', 'cnom']

class ParamedicalStaffForm(forms.ModelForm):
    class Meta:
        model = ParamedicalStaff
        fields = ['nom', 'prenom', 'cin', 'qualification']