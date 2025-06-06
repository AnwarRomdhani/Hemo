from django import forms
from .models import Transplantation, TransplantationRef, UserProfile,Center, MedicalActivity,TechnicalStaff, MedicalStaff, ParamedicalStaff, AdministrativeStaff, WorkerStaff, Governorate, Delegation, Membrane, Filtre, Machine, CNAM, Patient, TypeHemo, MethodHemo, HemodialysisSession, TransmittableDisease, TransmittableDiseaseRef, Complications, ComplicationsRef
import logging
import re
from django.contrib.auth.models import User
from .utils import send_verification_email

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
        self.center = kwargs.pop('center', None)
        super().__init__(*args, **kwargs)
        logger.debug("HEMO: Initializing AdministrativeStaffForm with raw data: %s", dict(self.data))
        if self.data and not any(k for k in self.data if k != 'csrfmiddlewaretoken'):
            logger.error("HEMO: Form initialized with empty data (excluding csrfmiddlewaretoken)")
            raise forms.ValidationError("Form data is empty. Please submit all required fields.")
        required_fields = ['nom', 'prenom', 'cin', 'job_title', 'role', 'username', 'email', 'password']
        if self.data:
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
        logger.debug("HEMO: Running clean with cleaned_data: %s", cleaned_data)
        required_fields = ['nom', 'prenom', 'cin', 'job_title', 'role', 'username', 'email', 'password']
        for field in required_fields:
            if field not in cleaned_data or cleaned_data[field] is None:
                logger.error("HEMO: Missing required field in cleaned_data: %s", field)
                self.add_error(field, f"{field.capitalize()} is required.")
        return cleaned_data

    def save(self, commit=True):
        logger.debug("HEMO: Starting save for AdministrativeStaffForm with cleaned data: %s", self.cleaned_data)
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
            profile = UserProfile.objects.create(user=user)
            verification_code = profile.generate_verification_code()
            try:
                send_verification_email(user, verification_code)
            except Exception as e:
                logger.error("HEMO: Failed to send verification email to %s: %s", email, str(e))
                raise forms.ValidationError(f"Failed to send verification email: {str(e)}")
        except Exception as e:
            logger.error("HEMO: Failed to create user %s: %s", username, str(e))
            raise forms.ValidationError(f"Failed to create user: {str(e)}")
        if self.center:
            staff.center = self.center
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

class MedicalStaffForm(forms.ModelForm):
    username = forms.CharField(max_length=150, label='Username', required=True)
    email = forms.EmailField(label='Email', required=True)
    password = forms.CharField(widget=forms.PasswordInput, label='Password', required=True)
    cnom = forms.CharField(max_length=100, label='CNOM', required=True)
    role = forms.ChoiceField(choices=MedicalStaff.ROLE_CHOICES, label='Role', initial='MEDICAL_PARA_STAFF', required=True)

    class Meta:
        model = MedicalStaff
        fields = ['nom', 'prenom', 'cin', 'cnom', 'role', 'username', 'email', 'password']
        widgets = {
            'nom': forms.TextInput(attrs={'placeholder': 'Last Name'}),
            'prenom': forms.TextInput(attrs={'placeholder': 'First Name'}),
            'cin': forms.TextInput(attrs={'placeholder': 'CIN'}),
            'cnom': forms.TextInput(attrs={'placeholder': 'CNOM'}),
            'role': forms.Select(),
            'username': forms.TextInput(attrs={'placeholder': 'Username'}),
            'email': forms.EmailInput(attrs={'placeholder': 'Email'}),
        }

    def __init__(self, *args, **kwargs):
        self.center = kwargs.pop('center', None)
        super().__init__(*args, **kwargs)
        logger.debug("HEMO: Initializing MedicalStaffForm with raw data: %s", dict(self.data))
        if self.data and not any(k for k in self.data if k != 'csrfmiddlewaretoken'):
            logger.error("HEMO: Form initialized with empty data (excluding csrfmiddlewaretoken)")
            raise forms.ValidationError("Form data is empty. Please submit all required fields.")
        required_fields = ['nom', 'prenom', 'cin', 'cnom', 'role', 'username', 'email', 'password']
        if self.data:
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
        if MedicalStaff.objects.filter(cin=cin).exists():
            logger.error("HEMO: Medical staff with CIN %s already exists", cin)
            raise forms.ValidationError("A staff member with this CIN already exists.")
        logger.debug("HEMO: CIN %s is unique", cin)
        return cin

    def clean_cnom(self):
        cnom = self.cleaned_data.get('cnom')
        logger.debug("HEMO: Cleaning CNOM: %s", cnom)
        if not cnom:
            logger.error("HEMO: CNOM is missing")
            raise forms.ValidationError("CNOM is required.")
        if MedicalStaff.objects.filter(cnom=cnom).exists():
            logger.error("HEMO: Medical staff with CNOM %s already exists", cnom)
            raise forms.ValidationError("A staff member with this CNOM already exists.")
        logger.debug("HEMO: CNOM %s is unique", cnom)
        return cnom

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
        logger.debug("HEMO: Running clean with cleaned_data: %s", cleaned_data)
        required_fields = ['nom', 'prenom', 'cin', 'cnom', 'role', 'username', 'email', 'password']
        for field in required_fields:
            if field not in cleaned_data or cleaned_data[field] is None:
                logger.error("HEMO: Missing required field in cleaned_data: %s", field)
                self.add_error(field, f"{field.capitalize()} is required.")
        return cleaned_data

    def save(self, commit=True):
        logger.debug("HEMO: Starting save for MedicalStaffForm with cleaned data: %s", self.cleaned_data)
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
            profile = UserProfile.objects.create(user=user)
            verification_code = profile.generate_verification_code()
            try:
                send_verification_email(user, verification_code)
            except Exception as e:
                logger.error("HEMO: Failed to send verification email to %s: %s", email, str(e))
                raise forms.ValidationError(f"Failed to send verification email: {str(e)}")
        except Exception as e:
            logger.error("HEMO: Failed to create user %s: %s", username, str(e))
            raise forms.ValidationError(f"Failed to create user: {str(e)}")
        if self.center:
            staff.center = self.center
        if commit:
            try:
                logger.debug("HEMO: Saving staff with user: %s (ID: %s)", staff.user, staff.user.id)
                staff.save()
                logger.info("HEMO: Saved MedicalStaff: %s %s (ID: %s, User ID: %s)",
                            staff.nom, staff.prenom, staff.id, staff.user.id)
            except Exception as e:
                logger.error("HEMO: Failed to save MedicalStaff: %s", str(e))
                if staff.user:
                    staff.user.delete()
                    logger.info("HEMO: Deleted orphaned user: %s", username)
                raise forms.ValidationError(f"Failed to save staff: {str(e)}")
        else:
            logger.debug("HEMO: Save deferred (commit=False)")
        return staff

class ParamedicalStaffForm(forms.ModelForm):
    username = forms.CharField(max_length=150, label='Username', required=True)
    email = forms.EmailField(label='Email', required=True)
    password = forms.CharField(widget=forms.PasswordInput, label='Password', required=True)
    qualification = forms.CharField(max_length=100, label='Qualification', required=True)
    role = forms.ChoiceField(choices=ParamedicalStaff.ROLE_CHOICES, label='Role', initial='MEDICAL_PARA_STAFF', required=True)

    class Meta:
        model = ParamedicalStaff
        fields = ['nom', 'prenom', 'cin', 'qualification', 'role', 'username', 'email', 'password']
        widgets = {
            'nom': forms.TextInput(attrs={'placeholder': 'Last Name'}),
            'prenom': forms.TextInput(attrs={'placeholder': 'First Name'}),
            'cin': forms.TextInput(attrs={'placeholder': 'CIN'}),
            'qualification': forms.TextInput(attrs={'placeholder': 'Qualification'}),
            'role': forms.Select(),
            'username': forms.TextInput(attrs={'placeholder': 'Username'}),
            'email': forms.EmailInput(attrs={'placeholder': 'Email'}),
        }

    def __init__(self, *args, **kwargs):
        self.center = kwargs.pop('center', None)
        super().__init__(*args, **kwargs)
        logger.debug("HEMO: Initializing ParamedicalStaffForm with raw data: %s", dict(self.data))
        if self.data and not any(k for k in self.data if k != 'csrfmiddlewaretoken'):
            logger.error("HEMO: Form initialized with empty data (excluding csrfmiddlewaretoken)")
            raise forms.ValidationError("Form data is empty. Please submit all required fields.")
        required_fields = ['nom', 'prenom', 'cin', 'qualification', 'role', 'username', 'email', 'password']
        if self.data:
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
        if ParamedicalStaff.objects.filter(cin=cin).exists():
            logger.error("HEMO: Paramedical staff with CIN %s already exists", cin)
            raise forms.ValidationError("A staff member with this CIN already exists.")
        logger.debug("HEMO: CIN %s is unique", cin)
        return cin

    def clean_qualification(self):
        qualification = self.cleaned_data.get('qualification')
        logger.debug("HEMO: Cleaning qualification: %s", qualification)
        if not qualification:
            logger.error("HEMO: Qualification is missing")
            raise forms.ValidationError("Qualification is required.")
        logger.debug("HEMO: Qualification %s is valid", qualification)
        return qualification

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
        logger.debug("HEMO: Running clean with cleaned_data: %s", cleaned_data)
        required_fields = ['nom', 'prenom', 'cin', 'qualification', 'role', 'username', 'email', 'password']
        for field in required_fields:
            if field not in cleaned_data or cleaned_data[field] is None:
                logger.error("HEMO: Missing required field in cleaned_data: %s", field)
                self.add_error(field, f"{field.capitalize()} is required.")
        return cleaned_data

    def save(self, commit=True):
        logger.debug("HEMO: Starting save for ParamedicalStaffForm with cleaned data: %s", self.cleaned_data)
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
            profile = UserProfile.objects.create(user=user)
            verification_code = profile.generate_verification_code()
            try:
                send_verification_email(user, verification_code)
            except Exception as e:
                logger.error("HEMO: Failed to send verification email to %s: %s", email, str(e))
                raise forms.ValidationError(f"Failed to send verification email: {str(e)}")
        except Exception as e:
            logger.error("HEMO: Failed to create user %s: %s", username, str(e))
            raise forms.ValidationError(f"Failed to create user: {str(e)}")
        if self.center:
            staff.center = self.center
        if commit:
            try:
                logger.debug("HEMO: Saving staff with user: %s (ID: %s)", staff.user, staff.user.id)
                staff.save()
                logger.info("HEMO: Saved ParamedicalStaff: %s %s (ID: %s, User ID: %s)",
                            staff.nom, staff.prenom, staff.id, staff.user.id)
            except Exception as e:
                logger.error("HEMO: Failed to save ParamedicalStaff: %s", str(e))
                if staff.user:
                    staff.user.delete()
                    logger.info("HEMO: Deleted orphaned user: %s", username)
                raise forms.ValidationError(f"Failed to save staff: {str(e)}")
        else:
            logger.debug("HEMO: Save deferred (commit=False)")
        return staff

class TechnicalStaffForm(forms.ModelForm):
    username = forms.CharField(max_length=150, label='Username', required=True)
    email = forms.EmailField(label='Email', required=True)
    password = forms.CharField(widget=forms.PasswordInput, label='Password', required=True)
    qualification = forms.CharField(max_length=100, label='Qualification', required=True)
    role = forms.ChoiceField(choices=TechnicalStaff.ROLE_CHOICES, label='Role', initial='TECHNICAL', required=True)

    class Meta:
        model = TechnicalStaff
        fields = ['nom', 'prenom', 'cin', 'qualification', 'role', 'username', 'email', 'password']
        widgets = {
            'nom': forms.TextInput(attrs={'placeholder': 'Last Name'}),
            'prenom': forms.TextInput(attrs={'placeholder': 'First Name'}),
            'cin': forms.TextInput(attrs={'placeholder': 'CIN'}),
            'qualification': forms.TextInput(attrs={'placeholder': 'Qualification'}),
            'role': forms.Select(),
            'username': forms.TextInput(attrs={'placeholder': 'Username'}),
            'email': forms.EmailInput(attrs={'placeholder': 'Email'}),
        }

    def __init__(self, *args, **kwargs):
        self.center = kwargs.pop('center', None)
        super().__init__(*args, **kwargs)
        logger.debug("HEMO: Initializing TechnicalStaffForm with raw data: %s", dict(self.data))
        if self.data and not any(k for k in self.data if k != 'csrfmiddlewaretoken'):
            logger.error("HEMO: Form initialized with empty data (excluding csrfmiddlewaretoken)")
            raise forms.ValidationError("Form data is empty. Please submit all required fields.")
        required_fields = ['nom', 'prenom', 'cin', 'qualification', 'role', 'username', 'email', 'password']
        if self.data:
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
        if TechnicalStaff.objects.filter(cin=cin).exists():
            logger.error("HEMO: Technical staff with CIN %s already exists", cin)
            raise forms.ValidationError("A staff member with this CIN already exists.")
        logger.debug("HEMO: CIN %s is unique", cin)
        return cin

    def clean_qualification(self):
        qualification = self.cleaned_data.get('qualification')
        logger.debug("HEMO: Cleaning qualification: %s", qualification)
        if not qualification:
            logger.error("HEMO: Qualification is missing")
            raise forms.ValidationError("Qualification is required.")
        logger.debug("HEMO: Qualification %s is valid", qualification)
        return qualification

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
        logger.debug("HEMO: Running clean with cleaned_data: %s", cleaned_data)
        required_fields = ['nom', 'prenom', 'cin', 'qualification', 'role', 'username', 'email', 'password']
        for field in required_fields:
            if field not in cleaned_data or cleaned_data[field] is None:
                logger.error("HEMO: Missing required field in cleaned_data: %s", field)
                self.add_error(field, f"{field.capitalize()} is required.")
        return cleaned_data

    def save(self, commit=True):
        logger.debug("HEMO: Starting save for TechnicalStaffForm with cleaned data: %s", self.cleaned_data)
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
            profile = UserProfile.objects.create(user=user)
            verification_code = profile.generate_verification_code()
            try:
                send_verification_email(user, verification_code)
            except Exception as e:
                logger.error("HEMO: Failed to send verification email to %s: %s", email, str(e))
                raise forms.ValidationError(f"Failed to send verification email: {str(e)}")
        except Exception as e:
            logger.error("HEMO: Failed to create user %s: %s", username, str(e))
            raise forms.ValidationError(f"Failed to create user: {str(e)}")
        if self.center:
            staff.center = self.center
        if commit:
            try:
                logger.debug("HEMO: Saving staff with user: %s (ID: %s)", staff.user, staff.user.id)
                staff.save()
                logger.info("HEMO: Saved TechnicalStaff: %s %s (ID: %s, User ID: %s)",
                            staff.nom, staff.prenom, staff.id, staff.user.id)
            except Exception as e:
                logger.error("HEMO: Failed to save TechnicalStaff: %s", str(e))
                if staff.user:
                    staff.user.delete()
                    logger.info("HEMO: Deleted orphaned user: %s", username)
                raise forms.ValidationError(f"Failed to save staff: {str(e)}")
        else:
            logger.debug("HEMO: Save deferred (commit=False)")
        return staff

class WorkerStaffForm(forms.ModelForm):
    username = forms.CharField(max_length=150, label='Username', required=True)
    email = forms.EmailField(label='Email', required=True)
    password = forms.CharField(widget=forms.PasswordInput, label='Password', required=True)
    job_title = forms.CharField(max_length=100, label='Job Title', required=True)
    role = forms.ChoiceField(choices=WorkerStaff.ROLE_CHOICES, label='Role', initial='VIEWER', required=True)

    class Meta:
        model = WorkerStaff
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
        self.center = kwargs.pop('center', None)
        super().__init__(*args, **kwargs)
        logger.debug("HEMO: Initializing WorkerStaffForm with raw data: %s", dict(self.data))
        if self.data and not any(k for k in self.data if k != 'csrfmiddlewaretoken'):
            logger.error("HEMO: Form initialized with empty data (excluding csrfmiddlewaretoken)")
            raise forms.ValidationError("Form data is empty. Please submit all required fields.")
        required_fields = ['nom', 'prenom', 'cin', 'job_title', 'role', 'username', 'email', 'password']
        if self.data:
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
        if WorkerStaff.objects.filter(cin=cin).exists():
            logger.error("HEMO: Worker staff with CIN %s already exists", cin)
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
        logger.debug("HEMO: Running clean with cleaned_data: %s", cleaned_data)
        required_fields = ['nom', 'prenom', 'cin', 'job_title', 'role', 'username', 'email', 'password']
        for field in required_fields:
            if field not in cleaned_data or cleaned_data[field] is None:
                logger.error("HEMO: Missing required field in cleaned_data: %s", field)
                self.add_error(field, f"{field.capitalize()} is required.")
        return cleaned_data

    def save(self, commit=True):
        logger.debug("HEMO: Starting save for WorkerStaffForm with cleaned data: %s", self.cleaned_data)
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
            profile = UserProfile.objects.create(user=user)
            verification_code = profile.generate_verification_code()
            try:
                send_verification_email(user, verification_code)
            except Exception as e:
                logger.error("HEMO: Failed to send verification email to %s: %s", email, str(e))
                raise forms.ValidationError(f"Failed to send verification email: {str(e)}")
        except Exception as e:
            logger.error("HEMO: Failed to create user %s: %s", username, str(e))
            raise forms.ValidationError(f"Failed to create user: {str(e)}")
        if self.center:
            staff.center = self.center
        if commit:
            try:
                logger.debug("HEMO: Saving staff with user: %s (ID: %s)", staff.user, staff.user.id)
                staff.save()
                logger.info("HEMO: Saved WorkerStaff: %s %s (ID: %s, User ID: %s)",
                            staff.nom, staff.prenom, staff.id, staff.user.id)
            except Exception as e:
                logger.error("HEMO: Failed to save WorkerStaff: %s", str(e))
                if staff.user:
                    staff.user.delete()
                    logger.info("HEMO: Deleted orphaned user: %s", username)
                raise forms.ValidationError(f"Failed to save staff: {str(e)}")
        else:
            logger.debug("HEMO: Save deferred (commit=False)")
        return staff

class VerificationForm(forms.Form):
    verification_code = forms.CharField(max_length=6, label='Verification Code', required=True)

    def clean_verification_code(self):
        code = self.cleaned_data.get('verification_code')
        if not code or not code.isdigit() or len(code) != 6:
            logger.error("Invalid verification code format: %s", code)
            raise forms.ValidationError("Verification code must be a 6-digit number.")
        return code


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


class PatientForm(forms.ModelForm):
    new_cnam_number = forms.CharField(max_length=50, required=False, label="New CNAM Number")
    weight = forms.FloatField(required=False, label="Weight (kg)", min_value=0, max_value=300, widget=forms.NumberInput(attrs={'placeholder': 'Weight (kg)', 'class': 'form-control'}))
    age = forms.IntegerField(required=False, label="Age (years)", min_value=0, max_value=120, widget=forms.NumberInput(attrs={'placeholder': 'Age (years)', 'class': 'form-control'}))

    class Meta:
        model = Patient
        fields = [
            'nom', 'prenom', 'cin', 'cnam', 'new_cnam_number', 'entry_date', 'previously_dialysed',
            'date_first_dia', 'blood_type', 'gender', 'weight', 'age', 'hypertension', 'diabetes'  # New fields
        ]
        widgets = {
            'nom': forms.TextInput(attrs={'placeholder': 'Last Name', 'class': 'form-control'}),
            'prenom': forms.TextInput(attrs={'placeholder': 'First Name', 'class': 'form-control'}),
            'cin': forms.TextInput(attrs={'placeholder': 'CIN', 'class': 'form-control'}),
            'cnam': forms.Select(attrs={'class': 'form-control'}),
            'entry_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'previously_dialysed': forms.CheckboxInput(attrs={'class': 'form-control'}),
            'date_first_dia': forms.DateInput(attrs={'type': 'date','class' : 'form-control'}),
            'blood_type': forms.Select(attrs={'class': 'form-control'}),
            'gender': forms.Select(attrs={'class': 'form-control'}),
            'hypertension': forms.CheckboxInput(attrs={'class': 'form-check-input'}),  # New field
            'diabetes': forms.CheckboxInput(attrs={'class': 'form-check-input'}),  # New field
        }

    def __init__(self, *args, **kwargs):
        self.center = kwargs.pop('center', None)
        super().__init__(*args, **kwargs)
        self.fields['cnam'].queryset = CNAM.objects.all()
        self.fields['cnam'].required = False
        self.fields['blood_type'].choices = Patient.BLOOD_TYPE_CHOICES
        self.fields['gender'].choices = Patient.GENDER_CHOICES
        self.fields['gender'].required = False
        self.fields['hypertension'].required = False  # New field
        self.fields['diabetes'].required = False  # New field

    def clean(self):
        cleaned_data = super().clean()
        cnam = cleaned_data.get('cnam')
        new_cnam_number = cleaned_data.get('new_cnam_number')
        previously_dialysed = cleaned_data.get('previously_dialysed')
        date_first_dia = cleaned_data.get('date_first_dia')
        weight = cleaned_data.get('weight')
        age = cleaned_data.get('age')

        # CNAM validation
        if not cnam and not new_cnam_number:
            self.add_error('new_cnam_number', "Select an existing CNAM number or provide a new one.")
        elif cnam and new_cnam_number:
            self.add_error('new_cnam_number', "Cannot select an existing CNAM and provide a new number.")

        # Previously dialysed validation
        if previously_dialysed and not date_first_dia:
            self.add_error('date_first_dia', "Date of first dialysis is required if previously dialysed.")
        if not previously_dialysed and date_first_dia:
            self.add_error('date_first_dia', "Date of first dialysis should not be set if not previously dialysed.")

        # Weight and age validation
        if weight is not None and (weight <= 0 or weight > 300):
            self.add_error('weight', "Weight must be between 0 and 300 kg.")
        if age is not None and (age < 0 or age > 120):
            self.add_error('age', "Age must be between 0 and 120 years.")

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        new_cnam_number = self.cleaned_data.get('new_cnam_number')
        if new_cnam_number:
            cnam, _ = CNAM.objects.get_or_create(number=new_cnam_number)
            instance.cnam = cnam
        if self.center:
            instance.center = self.center
        if commit:
            instance.save()
        return instance

class DeceasePatientForm(forms.ModelForm):
    class Meta:
        model = Patient
        fields = ['decease_note']
        widgets = {
            'decease_note': forms.Textarea(attrs={
                'placeholder': 'Enter notes on decease',
                'class': 'form-control',
                'rows': 4,
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['decease_note'].required = True  # Require note when declaring deceased

class HemodialysisSessionForm(forms.ModelForm):
    class Meta:
        model = HemodialysisSession
        fields = [
            'type', 'method', 'date_of_session', 'responsible_doc',
            'pre_dialysis_bp', 'during_dialysis_bp', 'post_dialysis_bp', 'heart_rate',
            'creatinine', 'urea', 'potassium', 'hemoglobin', 'hematocrit', 'albumin',
            'kt_v', 'urine_output', 'dry_weight', 'fluid_removal_rate', 'dialysis_duration',
            'vascular_access_type', 'dialyzer_type', 'severity_of_case',
        ]
        widgets = {
            'type': forms.Select(attrs={'class': 'form-control'}),
            'method': forms.Select(attrs={'class': 'form-control'}),
            'date_of_session': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'responsible_doc': forms.Select(attrs={'class': 'form-control'}),
            'pre_dialysis_bp': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1'}),
            'during_dialysis_bp': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1'}),
            'post_dialysis_bp': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1'}),
            'heart_rate': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1'}),
            'creatinine': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1'}),
            'urea': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1'}),
            'potassium': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1'}),
            'hemoglobin': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1'}),
            'hematocrit': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1'}),
            'albumin': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1'}),
            'kt_v': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1'}),
            'urine_output': forms.NumberInput(attrs={'class': 'form-control', 'step': '1'}),
            'dry_weight': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1'}),
            'fluid_removal_rate': forms.NumberInput(attrs={'class': 'form-control', 'step': '1'}),
            'dialysis_duration': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1'}),
            'vascular_access_type': forms.Select(attrs={'class': 'form-control'}),
            'dialyzer_type': forms.Select(attrs={'class': 'form-control'}),
            'severity_of_case': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        self.center = kwargs.pop('center', None)
        super().__init__(*args, **kwargs)
        logger.debug("HEMO: Initializing HemodialysisSessionForm with data: %s", self.data)
        if self.center:
            self.fields['responsible_doc'].queryset = MedicalStaff.objects.filter(center=self.center)
        self.fields['type'].queryset = TypeHemo.objects.all()
        self.fields['method'].queryset = MethodHemo.objects.all()
        # Core fields are required
        for field in ['type', 'method', 'date_of_session', 'responsible_doc']:
            self.fields[field].required = True
        # All other fields are optional
        for field in [
            'pre_dialysis_bp', 'during_dialysis_bp', 'post_dialysis_bp', 'heart_rate',
            'creatinine', 'urea', 'potassium', 'hemoglobin', 'hematocrit', 'albumin',
            'kt_v', 'urine_output', 'dry_weight', 'fluid_removal_rate', 'dialysis_duration',
            'vascular_access_type', 'dialyzer_type', 'severity_of_case',
        ]:
            self.fields[field].required = False

    def clean(self):
        cleaned_data = super().clean()
        logger.debug("HEMO: Cleaning form with cleaned_data: %s", cleaned_data)
        type_hemo = cleaned_data.get('type')
        method = cleaned_data.get('method')
        responsible_doc = cleaned_data.get('responsible_doc')
        pre_dialysis_bp = cleaned_data.get('pre_dialysis_bp')
        during_dialysis_bp = cleaned_data.get('during_dialysis_bp')
        post_dialysis_bp = cleaned_data.get('post_dialysis_bp')
        heart_rate = cleaned_data.get('heart_rate')
        creatinine = cleaned_data.get('creatinine')
        urea = cleaned_data.get('urea')
        potassium = cleaned_data.get('potassium')
        hemoglobin = cleaned_data.get('hemoglobin')
        hematocrit = cleaned_data.get('hematocrit')
        albumin = cleaned_data.get('albumin')
        kt_v = cleaned_data.get('kt_v')
        urine_output = cleaned_data.get('urine_output')
        dry_weight = cleaned_data.get('dry_weight')
        fluid_removal_rate = cleaned_data.get('fluid_removal_rate')
        dialysis_duration = cleaned_data.get('dialysis_duration')
        vascular_access_type = cleaned_data.get('vascular_access_type')
        dialyzer_type = cleaned_data.get('dialyzer_type')
        severity_of_case = cleaned_data.get('severity_of_case')

        # Validate type and method compatibility
        if type_hemo and method and method.type_hemo != type_hemo:
            self.add_error('method', 'Selected method does not belong to the chosen type.')

        # Validate responsible_doc center
        if responsible_doc and self.center and responsible_doc.center != self.center:
            self.add_error('responsible_doc', 'Selected doctor does not belong to this center.')

        # Ensure required fields
        required_fields = ['type', 'method', 'date_of_session', 'responsible_doc']
        for field in required_fields:
            if not cleaned_data.get(field):
                self.add_error(field, f'{field.replace("_", " ").title()} is required.')

        # Validate float fields
        for field, value, min_val, max_val, unit in [
            ('pre_dialysis_bp', pre_dialysis_bp, 50, 300, 'mmHg'),
            ('during_dialysis_bp', during_dialysis_bp, 50, 300, 'mmHg'),
            ('post_dialysis_bp', post_dialysis_bp, 50, 300, 'mmHg'),
            ('heart_rate', heart_rate, 30, 200, 'beats per minute'),
            ('creatinine', creatinine, 0.5, 20, 'mg/dL'),
            ('urea', urea, 10, 200, 'mg/dL'),
            ('potassium', potassium, 2, 8, 'mEq/L'),
            ('hemoglobin', hemoglobin, 5, 18, 'g/dL'),
            ('hematocrit', hematocrit, 15, 55, '%'),
            ('albumin', albumin, 2, 5.5, 'g/dL'),
            ('kt_v', kt_v, 0.5, 2.5, ''),
            ('urine_output', urine_output, 0, 2000, 'mL/day'),
            ('dry_weight', dry_weight, 30, 150, 'kg'),
            ('fluid_removal_rate', fluid_removal_rate, 0, 2000, 'mL/hour'),
            ('dialysis_duration', dialysis_duration, 1, 8, 'hours'),
        ]:
            if value is not None:
                if not isinstance(value, (int, float)):
                    self.add_error(field, f'{field.replace("_", " ").title()} must be a number.')
                elif value < min_val or value > max_val:
                    unit_str = f' {unit}' if unit else ''
                    self.add_error(field, f'{field.replace("_", " ").title()} must be between {min_val} and {max_val}{unit_str}.')

        # Validate choice fields
        if vascular_access_type and vascular_access_type not in ['Catheter', 'Graft', 'Fistula']:
            self.add_error('vascular_access_type', 'Invalid vascular access type.')
        if dialyzer_type and dialyzer_type not in ['High', 'Low']:
            self.add_error('dialyzer_type', 'Invalid dialyzer type.')
        if severity_of_case and severity_of_case not in ['Mild', 'Moderate', 'Severe']:
            self.add_error('severity_of_case', 'Invalid severity level.')

        return cleaned_data

    def save(self, commit=True):
        logger.debug("HEMO: Saving HemodialysisSessionForm with cleaned_data: %s", self.cleaned_data)
        session = super().save(commit=False)
        if commit:
            try:
                session.save()
                logger.info("HEMO: Saved HemodialysisSession with ID: %s", session.id)
            except Exception as e:
                logger.error("HEMO: Failed to save HemodialysisSession: %s", str(e))
                raise
        return session

class TransmittableDiseaseForm(forms.ModelForm):
    new_disease_name = forms.CharField(max_length=255, required=False, label="New Disease Name")

    def __init__(self, *args, **kwargs):
        self.center = kwargs.pop('center', None)
        super().__init__(*args, **kwargs)
        logger.debug("TRANS: Initializing TransmittableDiseaseForm with data: %s", self.data)
        self.fields['disease'].queryset = TransmittableDiseaseRef.objects.all()
        self.fields['disease'].required = False

    class Meta:
        model = TransmittableDisease
        fields = ['disease', 'new_disease_name', 'date_of_contraction']
        widgets = {
            'date_of_contraction': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'disease': forms.Select(attrs={'class': 'form-control'}),
            'new_disease_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter new disease name'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        logger.debug("TRANS: Cleaning form with cleaned_data: %s", cleaned_data)
        disease = cleaned_data.get('disease')
        new_disease_name = cleaned_data.get('new_disease_name')
        date_of_contraction = cleaned_data.get('date_of_contraction')

        if not (disease or new_disease_name):
            self.add_error('disease', 'Either select a disease or enter a new disease name.')
            self.add_error('new_disease_name', 'Either enter a new disease name or select a disease.')
        elif disease and new_disease_name:
            self.add_error('disease', 'Select only one: existing disease or new disease name.')
            self.add_error('new_disease_name', 'Select only one: new disease name or existing disease.')

        if not date_of_contraction:
            self.add_error('date_of_contraction', 'Date of Contraction is required.')

        if new_disease_name and TransmittableDiseaseRef.objects.filter(label_disease__iexact=new_disease_name).exists():
            self.add_error('new_disease_name', 'A disease with this name already exists.')

        return cleaned_data

class TransmittableDiseaseRefForm(forms.ModelForm):
    class Meta:
        model = TransmittableDiseaseRef
        fields = ['label_disease', 'type_of_transmission']

class ComplicationsForm(forms.ModelForm):
    new_complication_name = forms.CharField(max_length=255, required=False, label="New Complication Name")

    def __init__(self, *args, **kwargs):
        self.center = kwargs.pop('center', None)
        super().__init__(*args, **kwargs)
        logger.debug("COMP: Initializing ComplicationsForm with data: %s", self.data)
        self.fields['complication'].queryset = ComplicationsRef.objects.all()
        self.fields['complication'].required = False

    class Meta:
        model = Complications
        fields = ['complication', 'new_complication_name', 'notes', 'date_of_contraction']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 4, 'cols': 50, 'class': 'form-control'}),
            'date_of_contraction': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'complication': forms.Select(attrs={'class': 'form-control'}),
            'new_complication_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter new complication name'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        logger.debug("COMP: Cleaning form with cleaned_data: %s", cleaned_data)
        complication = cleaned_data.get('complication')
        new_complication_name = cleaned_data.get('new_complication_name')
        date_of_contraction = cleaned_data.get('date_of_contraction')

        if not (complication or new_complication_name):
            self.add_error('complication', 'Either select a complication or enter a new complication name.')
            self.add_error('new_complication_name', 'Either enter a new complication name or select a complication.')
        elif complication and new_complication_name:
            self.add_error('complication', 'Select only one: existing complication or new complication name.')
            self.add_error('new_complication_name', 'Select only one: new complication name or existing complication.')

        if not date_of_contraction:
            self.add_error('date_of_contraction', 'Date of Contraction is required.')

        if new_complication_name and ComplicationsRef.objects.filter(label_complication__iexact=new_complication_name).exists():
            self.add_error('new_complication_name', 'A complication with this name already exists.')

        return cleaned_data


class ComplicationsRefForm(forms.ModelForm):
    class Meta:
        model = ComplicationsRef
        fields = ['label_complication']



class TransplantationForm(forms.ModelForm):
    new_transplantation_name = forms.CharField(max_length=255, required=False, label="New Transplantation Name")

    def __init__(self, *args, **kwargs):
        self.center = kwargs.pop('center', None)
        super().__init__(*args, **kwargs)
        logger.debug("TRANSPLANT: Initializing TransplantationForm with data: %s", self.data)
        self.fields['transplantation'].queryset = TransplantationRef.objects.all()
        self.fields['transplantation'].required = False

    class Meta:
        model = Transplantation
        fields = ['transplantation', 'new_transplantation_name', 'date_operation', 'notes']
        widgets = {
            'date_operation': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'transplantation': forms.Select(attrs={'class': 'form-control'}),
            'new_transplantation_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter new transplantation name'}),
            'notes': forms.Textarea(attrs={'rows': 4, 'cols': 50, 'class': 'form-control'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        logger.debug("TRANSPLANT: Cleaning form with cleaned_data: %s", cleaned_data)
        transplantation = cleaned_data.get('transplantation')
        new_transplantation_name = cleaned_data.get('new_transplantation_name')
        date_operation = cleaned_data.get('date_operation')

        if not (transplantation or new_transplantation_name):
            self.add_error('transplantation', 'Either select a transplantation or enter a new transplantation name.')
            self.add_error('new_transplantation_name', 'Either enter a new transplantation name or select a transplantation.')
        elif transplantation and new_transplantation_name:
            self.add_error('transplantation', 'Select only one: existing transplantation or new transplantation name.')
            self.add_error('new_transplantation_name', 'Select only one: new transplantation name or existing transplantation.')

        if not date_operation:
            self.add_error('date_operation', 'Date of Operation is required.')

        if new_transplantation_name and TransplantationRef.objects.filter(label_transplantation__iexact=new_transplantation_name).exists():
            self.add_error('new_transplantation_name', 'A transplantation with this name already exists.')

        return cleaned_data
    
class TransplantationRefForm(forms.ModelForm):
    class Meta:
        model = TransplantationRef
        fields = ['label_transplantation']
        widgets = {
            'label_transplantation': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter transplantation label'
            }),
        }