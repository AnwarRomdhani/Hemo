from django import forms
from .models import Center, TechnicalStaff, MedicalStaff, ParamedicalStaff

class CenterForm(forms.ModelForm):
    class Meta:
        model = Center
        fields = ['sub_domain', 'tel', 'label', 'state', 'private', 'mail', 
                 'government_code', 'delegate_code', 'name_delegate',
                 'type_center', 'code_type_hemo', 'name_type_hemo']
        widgets = {
            'sub_domain': forms.TextInput(attrs={
                'placeholder': 'subdomain-name',
                'class': 'form-control'
            }),
            'tel': forms.NumberInput(attrs={
                'placeholder': 'Phone number',
                'class': 'form-control'
            }),
            'label': forms.TextInput(attrs={
                'placeholder': 'Center label',
                'class': 'form-control'
            }),
            'state': forms.TextInput(attrs={
                'placeholder': 'State',
                'class': 'form-control'
            }),
            'mail': forms.EmailInput(attrs={
                'placeholder': 'Email',
                'class': 'form-control'
            }),
            'government_code': forms.TextInput(attrs={
                'placeholder': 'Government Code',
                'class': 'form-control public-field'
            }),
            'delegate_code': forms.TextInput(attrs={
                'placeholder': 'Delegate Code',
                'class': 'form-control public-field'
            }),
            'name_delegate': forms.TextInput(attrs={
                'placeholder': 'Delegate Name',
                'class': 'form-control public-field'
            }),
            'type_center': forms.TextInput(attrs={
                'placeholder': 'Type of Center',
                'class': 'form-control public-field'
            }),
            'code_type_hemo': forms.TextInput(attrs={
                'placeholder': 'Hemo Code',
                'class': 'form-control public-field'
            }),
            'name_type_hemo': forms.TextInput(attrs={
                'placeholder': 'Hemo Name',
                'class': 'form-control public-field'
            }),
            'private': forms.CheckboxInput(attrs={
                'class': 'center-type-toggle',
                'onchange': "togglePublicFields(this)"
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Initially hide public fields if private is checked
        if self.instance and self.instance.private:
            for field in ['government_code', 'delegate_code', 'name_delegate',
                         'type_center', 'code_type_hemo', 'name_type_hemo']:
                self.fields[field].widget.attrs['style'] = 'display:none;'

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