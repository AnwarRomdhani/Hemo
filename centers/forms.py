from django import forms
from .models import Center, TechnicalStaff, MedicalStaff, ParamedicalStaff, Governorate, Delegation, Membrane, Filtre, Machine
import logging

logger = logging.getLogger(__name__)

class CenterForm(forms.ModelForm):
    class Meta:
        model = Center
        fields = ['sub_domain', 'tel', 'label', 'mail', 'adresse', 'center_code', 'type_center', 'governorate', 'delegation', 'code_type_hemo', 'name_type_hemo']
        widgets = {
            'delegation': forms.Select(attrs={'disabled': False}),
            'center_code': forms.TextInput(attrs={'placeholder': 'Center Code', 'class': 'form-control'}),
            'type_center': forms.Select(attrs={'class': 'form-control'}),
            'code_type_hemo': forms.Select(attrs={'class': 'form-control'}),
            'name_type_hemo': forms.Select(attrs={'class': 'form-control'}),
            'adresse': forms.TextInput(attrs={'placeholder': 'Address', 'class': 'form-control'}),  # Widget for adresse
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['delegation'].queryset = Delegation.objects.none()
        if 'governorate' in self.data:
            try:
                governorate_id = int(self.data.get('governorate'))
                self.fields['delegation'].queryset = Delegation.objects.filter(governorate_id=governorate_id).order_by('name')
                logger.debug("Delegation queryset for governorate %s: %s", governorate_id, list(self.fields['delegation'].queryset.values('id', 'name')))
            except (ValueError, TypeError):
                logger.warning("Invalid governorate_id: %s", self.data.get('governorate'))
        elif self.instance.pk and self.instance.governorate:
            self.fields['delegation'].queryset = Delegation.objects.filter(governorate=self.instance.governorate).order_by('name')
            logger.debug("Delegation queryset for instance governorate %s: %s", self.instance.governorate_id, list(self.fields['delegation'].queryset.values('id', 'name')))

    def clean_delegation(self):
        delegation = self.cleaned_data.get('delegation')
        governorate = self.cleaned_data.get('governorate')
        if delegation and governorate and delegation.governorate != governorate:
            logger.error("Invalid delegation %s for governorate %s", delegation, governorate)
            raise forms.ValidationError("Selected delegation does not belong to the chosen governorate.")
        return delegation

    def clean_center_code(self):
        center_code = self.cleaned_data.get('center_code')
        if center_code:
            try:
                center_code = int(center_code)
            except (ValueError, TypeError):
                logger.error("Invalid center_code: %s", center_code)
                raise forms.ValidationError("Center code must be a valid integer.")
        else:
            center_code = None
        return center_code

    def clean(self):
        cleaned_data = super().clean()
        type_center = cleaned_data.get('type_center')
        code_type_hemo = cleaned_data.get('code_type_hemo')
        name_type_hemo = cleaned_data.get('name_type_hemo')

        if type_center != 'PRIVATE':
            if not code_type_hemo:
                self.add_error('code_type_hemo', "Hemodialysis code is required for non-private centers.")
            if not name_type_hemo:
                self.add_error('name_type_hemo', "Hemodialysis type name is required for non-private centers.")
        return cleaned_data

class BaseStaffForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.center = kwargs.pop('center', None)
        super().__init__(*args, **kwargs)
        if 'center' in self.fields:
            del self.fields['center']

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.center:
            instance.center = self.center
        if commit:
            instance.save()
        return instance

class TechnicalStaffForm(BaseStaffForm):
    class Meta:
        model = TechnicalStaff
        fields = ['nom', 'prenom', 'cin', 'qualification']
        widgets = {
            'nom': forms.TextInput(attrs={'placeholder': 'Last Name', 'class': 'form-control'}),
            'prenom': forms.TextInput(attrs={'placeholder': 'First Name', 'class': 'form-control'}),
            'cin': forms.TextInput(attrs={'placeholder': 'CIN', 'class': 'form-control'}),
            'qualification': forms.TextInput(attrs={'placeholder': 'Qualification', 'class': 'form-control'}),
        }

class MedicalStaffForm(BaseStaffForm):
    class Meta:
        model = MedicalStaff
        fields = ['nom', 'prenom', 'cin', 'cnom']
        widgets = {
            'nom': forms.TextInput(attrs={'placeholder': 'Last Name', 'class': 'form-control'}),
            'prenom': forms.TextInput(attrs={'placeholder': 'First Name', 'class': 'form-control'}),
            'cin': forms.TextInput(attrs={'placeholder': 'CIN', 'class': 'form-control'}),
            'cnom': forms.TextInput(attrs={'placeholder': 'CNOM', 'class': 'form-control'}),
        }

class ParamedicalStaffForm(BaseStaffForm):
    class Meta:
        model = ParamedicalStaff
        fields = ['nom', 'prenom', 'cin', 'qualification']
        widgets = {
            'nom': forms.TextInput(attrs={'placeholder': 'Last Name', 'class': 'form-control'}),
            'prenom': forms.TextInput(attrs={'placeholder': 'First Name', 'class': 'form-control'}),
            'cin': forms.TextInput(attrs={'placeholder': 'CIN', 'class': 'form-control'}),
            'qualification': forms.TextInput(attrs={'placeholder': 'Qualification', 'class': 'form-control'}),
        }

class MachineForm(forms.ModelForm):
    new_membrane_type = forms.CharField(max_length=100, required=False, label="New Membrane Type")
    new_filtre_type = forms.CharField(max_length=100, required=False, label="New Filtre Type")
    sterilisation = forms.MultipleChoiceField(
        choices=Filtre.STERILISATION_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Filtre Sterilisation Methods"
    )

    class Meta:
        model = Machine
        fields = ['brand', 'functional', 'reserve', 'refurbished', 'nbre_hrs', 'membrane', 'filtre']
        widgets = {
            'brand': forms.TextInput(attrs={'placeholder': 'Brand', 'class': 'form-control'}),
            'functional': forms.CheckboxInput(attrs={'class': 'form-control'}),
            'reserve': forms.CheckboxInput(attrs={'class': 'form-control'}),
            'refurbished': forms.CheckboxInput(attrs={'class': 'form-control'}),
            'nbre_hrs': forms.NumberInput(attrs={'placeholder': 'Hours of Operation', 'class': 'form-control'}),
            'membrane': forms.Select(attrs={'class': 'form-control'}),
            'filtre': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        self.center = kwargs.pop('center', None)
        super().__init__(*args, **kwargs)
        self.fields['membrane'].queryset = Membrane.objects.all()
        self.fields['membrane'].required = False
        self.fields['filtre'].queryset = Filtre.objects.all()
        self.fields['filtre'].required = False

    def clean(self):
        cleaned_data = super().clean()
        membrane = cleaned_data.get('membrane')
        new_membrane_type = cleaned_data.get('new_membrane_type')
        filtre = cleaned_data.get('filtre')
        new_filtre_type = cleaned_data.get('new_filtre_type')
        sterilisation = cleaned_data.get('sterilisation')

        if not membrane and not new_membrane_type:
            self.add_error('new_membrane_type', "Select an existing membrane or provide a new membrane type.")
        elif membrane and new_membrane_type:
            self.add_error('new_membrane_type', "Cannot select an existing membrane and provide a new type.")

        if not filtre and not new_filtre_type:
            self.add_error('new_filtre_type', "Select an existing filtre or provide a new filtre type.")
        elif filtre and new_filtre_type:
            self.add_error('new_filtre_type', "Cannot select an existing filtre and provide a new type.")
        elif new_filtre_type and not sterilisation:
            self.add_error('sterilisation', "Sterilisation methods are required when creating a new filtre.")

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        new_membrane_type = self.cleaned_data.get('new_membrane_type')
        new_filtre_type = self.cleaned_data.get('new_filtre_type')
        sterilisation = self.cleaned_data.get('sterilisation')

        if new_membrane_type:
            membrane, _ = Membrane.objects.get_or_create(type=new_membrane_type)
            instance.membrane = membrane

        if new_filtre_type:
            sterilisation_str = ','.join(sterilisation) if sterilisation else ''
            filtre, _ = Filtre.objects.get_or_create(
                type=new_filtre_type,
                defaults={'sterilisation': sterilisation_str}
            )
            instance.filtre = filtre

        if self.center:
            instance.center = self.center

        if commit:
            instance.save()
        return instance