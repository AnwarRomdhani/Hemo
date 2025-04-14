from django import forms
from .models import Center, TechnicalStaff, MedicalStaff, ParamedicalStaff


class CenterForm(forms.ModelForm):
    class Meta:
        model = Center
        fields = ['sub_domain', 'tel', 'nom', 'state', 'private', 'mail']
        widgets = {
            'sub_domain': forms.TextInput(attrs={'placeholder': 'subdomain-name'}),
            'tel': forms.NumberInput(attrs={'placeholder': 'Phone number'}),
            'nom': forms.TextInput(attrs={'placeholder': 'Center name'}),
            'state': forms.TextInput(attrs={'placeholder': 'State'}),
            'mail': forms.EmailInput(attrs={'placeholder': 'Email'}),
        }


class TechnicalStaffForm(forms.ModelForm):
    class Meta:
        model = TechnicalStaff
        fields = ['nom', 'prenom', 'cin', 'center', 'qualification']
        widgets = {
            'nom': forms.TextInput(attrs={'placeholder': 'Last Name'}),
            'prenom': forms.TextInput(attrs={'placeholder': 'First Name'}),
            'cin': forms.TextInput(attrs={'placeholder': 'CIN'}),
            'qualification': forms.TextInput(attrs={'placeholder': 'Qualification'}),
        }


class MedicalStaffForm(forms.ModelForm):
    class Meta:
        model = MedicalStaff
        fields = ['nom', 'prenom', 'cin', 'center', 'cnom']
        widgets = {
            'nom': forms.TextInput(attrs={'placeholder': 'Last Name'}),
            'prenom': forms.TextInput(attrs={'placeholder': 'First Name'}),
            'cin': forms.TextInput(attrs={'placeholder': 'CIN'}),
            'cnom': forms.TextInput(attrs={'placeholder': 'CNOM'}),
        }


class ParamedicalStaffForm(forms.ModelForm):
    class Meta:
        model = ParamedicalStaff
        fields = ['nom', 'prenom', 'cin', 'center', 'qualification']
        widgets = {
            'nom': forms.TextInput(attrs={'placeholder': 'Last Name'}),
            'prenom': forms.TextInput(attrs={'placeholder': 'First Name'}),
            'cin': forms.TextInput(attrs={'placeholder': 'CIN'}),
            'qualification': forms.TextInput(attrs={'placeholder': 'Qualification'}),
        }
