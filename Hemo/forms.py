from django import forms
from centers.models import Center, TechnicalStaff, MedicalStaff, ParamedicalStaff, AdministrativeStaff, WorkerStaff, Governorate, Delegation, Membrane, Filtre, Machine, CNAM, Patient, TypeHemo, MethodHemo, HemodialysisSession, TransmittableDisease, TransmittableDiseaseRef, Complications, ComplicationsRef
import logging
from django.contrib.auth.models import User
import re

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
            'adresse': forms.TextInput(attrs={'placeholder': 'Address', 'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['delegation'].queryset = Delegation.objects.none()
        if 'governorate' in self.data:
            try:
                governorate_id = int(self.data.get('governorate'))
                self.fields['delegation'].queryset = Delegation.objects.filter(governorate_id=governorate_id).order_by('name')
                logger.debug("HEMO: Delegation queryset for governorate %s: %s", governorate_id, list(self.fields['delegation'].queryset.values('id', 'name')))
            except (ValueError, TypeError):
                logger.warning("HEMO: Invalid governorate_id: %s", self.data.get('governorate'))
        elif self.instance.pk and self.instance.governorate:
            self.fields['delegation'].queryset = Delegation.objects.filter(governorate=self.instance.governorate).order_by('name')
            logger.debug("HEMO: Delegation queryset for instance governorate %s: %s", self.instance.governorate_id, list(self.fields['delegation'].queryset.values('id', 'name')))

    def clean_delegation(self):
        delegation = self.cleaned_data.get('delegation')
        governorate = self.cleaned_data.get('governorate')
        if delegation and governorate and delegation.governorate != governorate:
            logger.error("HEMO: Invalid delegation %s for governorate %s", delegation, governorate)
            raise forms.ValidationError("Selected delegation does not belong to the chosen governorate.")
        return delegation

    def clean_center_code(self):
        center_code = self.cleaned_data.get('center_code')
        if center_code:
            try:
                center_code = int(center_code)
            except (ValueError, TypeError):
                logger.error("HEMO: Invalid center_code: %s", center_code)
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

class AdministrativeStaffForm(forms.ModelForm):
    username = forms.CharField(max_length=150, label='Username', required=True)
    email = forms.EmailField(label='Email', required=True)
    password = forms.CharField(widget=forms.PasswordInput, label='Password', required=True)
    job_title = forms.CharField(max_length=100, label='Job Title', required=True)
    role = forms.ChoiceField(choices=AdministrativeStaff.ROLE_CHOICES, label='Role', initial='VIEWER', required=True)

    class Meta:
        model = AdministrativeStaff
        fields = ['nom', 'prenom', 'cin', 'job_title', 'role', 'username', 'email', 'password']
        widgets = {
            'nom': forms.TextInput(attrs={'placeholder': 'Last Name'}),
            'prenom': forms.TextInput(attrs={'placeholder': 'First Name'}),
            'cin': forms.TextInput(attrs={'placeholder': 'CIN'}),
            'job_title': forms.TextInput(attrs={'placeholder': 'Job Title'}),
            'role': forms.Select(),
            'username': forms.TextInput(attrs={'placeholder': 'Username'}),
            'email': forms.EmailInput(attrs={'placeholder': 'Email'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        logger.debug("HEMO: Initializing Hemo AdministrativeStaffForm with raw data: %s", dict(self.data))
        if not any(k for k in self.data if k != 'csrfmiddlewaretoken'):
            logger.error("HEMO: Form initialized with empty data (excluding csrfmiddlewaretoken)")
            raise forms.ValidationError("Form data is empty. Please submit all required fields.")
        required_fields = ['nom', 'prenom', 'cin', 'job_title', 'role', 'username', 'email', 'password']
        for field in required_fields:
            if field not in self.data or not self.data[field]:
                logger.error("HEMO: Missing or empty required field in form data: %s", field)
                self.add_error(field, f"{field.capitalize()} is required.")

    def clean_cin(self):
        cin = self.cleaned_data.get('cin')
        logger.debug("HEMO: Cleaning CIN: %s", cin)
        if not cin:
            logger.error("HEMO: CIN is missing")
            raise forms.ValidationError("CIN is required.")
        if AdministrativeStaff.objects.filter(cin=cin).exists():
            logger.error("HEMO: Administrative staff with CIN %s already exists", cin)
            raise forms.ValidationError("A staff member with this CIN already exists.")
        logger.debug("HEMO: CIN %s is unique", cin)
        return cin

    def clean_username(self):
        username = self.cleaned_data.get('username')
        logger.debug("HEMO: Cleaning username: %s", username)
        if not username:
            logger.error("HEMO: Username is missing")
            raise forms.ValidationError("Username is required.")
        if not re.match(r'^[a-zA-Z0-9]+$', username):
            logger.error("HEMO: Username %s contains invalid characters", username)
            raise forms.ValidationError("Username must be alphanumeric.")
        if User.objects.filter(username=username).exists():
            logger.error("HEMO: Username %s already exists", username)
            raise forms.ValidationError("This username is already taken.")
        logger.debug("HEMO: Username %s is valid and unique", username)
        return username

    def clean_email(self):
        email = self.cleaned_data.get('email')
        logger.debug("HEMO: Cleaning email: %s", email)
        if not email:
            logger.error("HEMO: Email is missing")
            raise forms.ValidationError("Email is required.")
        if User.objects.filter(email=email).exists():
            logger.error("HEMO: Email %s already exists", email)
            raise forms.ValidationError("This email is already taken.")
        logger.debug("HEMO: Email %s is valid and unique", email)
        return email

    def clean_password(self):
        password = self.cleaned_data.get('password')
        logger.debug("HEMO: Cleaning password: %s", password)
        if not password:
            logger.error("HEMO: Password is missing")
            raise forms.ValidationError("Password is required.")
        if len(password) < 8:
            logger.error("HEMO: Password too short for username %s", self.cleaned_data.get('username', 'unknown'))
            raise forms.ValidationError("Password must be at least 8 characters long.")
        logger.debug("HEMO: Password is valid")
        return password

    def clean(self):
        cleaned_data = super().clean()
        logger.debug("HEMO: Cleaned data: %s", cleaned_data)
        required_fields = ['nom', 'prenom', 'cin', 'job_title', 'role', 'username', 'email', 'password']
        for field in required_fields:
            if field not in cleaned_data or cleaned_data[field] is None:
                logger.error("HEMO: Missing required field in cleaned_data: %s", field)
                self.add_error(field, f"{field.capitalize()} is required.")
        return cleaned_data

    def save(self, commit=True):
        logger.debug("HEMO: Starting save for Hemo AdministrativeStaffForm with cleaned data: %s", self.cleaned_data)
        staff = super().save(commit=False)
        username = self.cleaned_data.get('username')
        email = self.cleaned_data.get('email')
        password = self.cleaned_data.get('password')

        if not all([username, email, password]):
            logger.error("HEMO: Missing required fields for user creation: username=%s, email=%s, password=%s",
                        username, email, password)
            raise forms.ValidationError("Username, email, and password are required for user creation.")

        logger.debug("HEMO: Attempting to create user: %s", username)
        try:
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password
            )
            logger.info("HEMO: Created new user: %s (ID: %s)", username, user.id)
            staff.user = user
        except Exception as e:
            logger.error("HEMO: Failed to create user %s: %s", username, str(e))
            raise forms.ValidationError(f"Failed to create user: {str(e)}")

        if commit:
            try:
                logger.debug("HEMO: Saving staff with user: %s (ID: %s)", staff.user, staff.user.id)
                staff.save()
                logger.info("HEMO: Saved AdministrativeStaff: %s %s (ID: %s, User ID: %s)", 
                           staff.nom, staff.prenom, staff.id, staff.user.id)
            except Exception as e:
                logger.error("HEMO: Failed to save AdministrativeStaff: %s", str(e))
                if staff.user:
                    staff.user.delete()
                    logger.info("HEMO: Deleted orphaned user: %s", username)
                raise forms.ValidationError(f"Failed to save staff: {str(e)}")
        else:
            logger.debug("HEMO: Save deferred (commit=False)")
        return staff