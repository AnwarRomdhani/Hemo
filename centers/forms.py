from django import forms
from .models import Center, TechnicalStaff, MedicalStaff, ParamedicalStaff, AdministrativeStaff, WorkerStaff, Governorate, Delegation, Membrane, Filtre, Machine, CNAM, Patient, TypeHemo, MethodHemo, HemodialysisSession, TransmittableDisease, TransmittableDiseaseRef, Complications, ComplicationsRef
import logging
import re
from django.contrib.auth.models import User

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

class TechnicalStaffForm(forms.ModelForm):
    username = forms.CharField(max_length=150, label='Username', required=True)
    email = forms.EmailField(label='Email', required=True)
    password = forms.CharField(widget=forms.PasswordInput, label='Password', required=True)
    qualification = forms.CharField(max_length=100, label='Qualification', required=True)
    role = forms.ChoiceField(choices=TechnicalStaff.ROLE_CHOICES, label='Role', initial='VIEWER', required=True)

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
        # Only validate data presence on POST requests
        if self.data and not any(k for k in self.data if k != 'csrfmiddlewaretoken'):
            logger.error("HEMO: Form initialized with empty data (excluding csrfmiddlewaretoken)")
            raise forms.ValidationError("Form data is empty. Please submit all required fields.")
        required_fields = ['nom', 'prenom', 'cin', 'qualification', 'role', 'username', 'email', 'password']
        if self.data:  # Only check on POST
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
        password = cleaned_data.get('password')
        if password and len(password) < 8:
            logger.error("HEMO: Password too short in clean: %s", password)
            self.add_error('password', "Password must be at least 8 characters long.")
        logger.debug("HEMO: Clean completed: %s", cleaned_data)
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

class MedicalStaffForm(forms.ModelForm):
    username = forms.CharField(max_length=150, label='Username', required=True)
    email = forms.EmailField(label='Email', required=True)
    password = forms.CharField(widget=forms.PasswordInput, label='Password', required=True)
    cnom = forms.CharField(max_length=100, label='CNOM', required=True)
    role = forms.ChoiceField(choices=MedicalStaff.ROLE_CHOICES, label='Role', initial='VIEWER', required=True)

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
        # Only validate data presence on POST requests
        if self.data and not any(k for k in self.data if k != 'csrfmiddlewaretoken'):
            logger.error("HEMO: Form initialized with empty data (excluding csrfmiddlewaretoken)")
            raise forms.ValidationError("Form data is empty. Please submit all required fields.")
        required_fields = ['nom', 'prenom', 'cin', 'cnom', 'role', 'username', 'email', 'password']
        if self.data:  # Only check on POST
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
        password = cleaned_data.get('password')
        if password and len(password) < 8:
            logger.error("HEMO: Password too short in clean: %s", password)
            self.add_error('password', "Password must be at least 8 characters long.")
        logger.debug("HEMO: Clean completed: %s", cleaned_data)
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
    username = forms.CharField(max_length=150, required=True)
    email = forms.EmailField(required=True)
    password = forms.CharField(widget=forms.PasswordInput, required=True)

    class Meta:
        model = ParamedicalStaff
        fields = ['nom', 'prenom', 'cin', 'qualification', 'role', 'username', 'email', 'password']

    def __init__(self, *args, **kwargs):
        self.center = kwargs.pop('center', None)
        super().__init__(*args, **kwargs)
        if not self.center:
            logger.warning("No center provided for ParamedicalStaffForm")
            raise ValueError("Center is required for ParamedicalStaffForm")

    def clean(self):
        cleaned_data = super().clean()
        if self.instance.pk is None:  # Only for new instances
            username = cleaned_data.get('username')
            email = cleaned_data.get('email')
            if User.objects.filter(username=username).exists():
                self.add_error('username', "A user with this username already exists.")
            if User.objects.filter(email=email).exists():
                self.add_error('email', "A user with this email already exists.")
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
        except Exception as e:
            logger.error("HEMO: Failed to create user %s: %s", username, str(e))
            raise forms.ValidationError(f"Failed to create user: {str(e)}")

        if self.center:
            staff.center = self.center
            logger.debug("HEMO: Assigned center %s to staff", self.center.label)
        else:
            logger.error("HEMO: No center provided for staff")
            raise forms.ValidationError("Center is required for staff creation.")

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
        logger.debug("HEMO: Initializing Hemo AdministrativeStaffForm with raw data: %s", dict(self.data))
        # Only validate data presence on POST requests
        if self.data and not any(k for k in self.data if k != 'csrfmiddlewaretoken'):
            logger.error("HEMO: Form initialized with empty data (excluding csrfmiddlewaretoken)")
            raise forms.ValidationError("Form data is empty. Please submit all required fields.")
        required_fields = ['nom', 'prenom', 'cin', 'job_title', 'role', 'username', 'email', 'password']
        if self.data:  # Only check on POST
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
        password = cleaned_data.get('password')
        if password and len(password) < 8:
            logger.error("HEMO: Password too short in clean: %s", password)
            self.add_error('password', "Password must be at least 8 characters long.")
        logger.debug("HEMO: Clean completed: %s", cleaned_data)
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
        # Only validate data presence on POST requests
        if self.data and not any(k for k in self.data if k != 'csrfmiddlewaretoken'):
            logger.error("HEMO: Form initialized with empty data (excluding csrfmiddlewaretoken)")
            raise forms.ValidationError("Form data is empty. Please submit all required fields.")
        required_fields = ['nom', 'prenom', 'cin', 'job_title', 'role', 'username', 'email', 'password']
        if self.data:  # Only check on POST
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
        password = cleaned_data.get('password')
        if password and len(password) < 8:
            logger.error("HEMO: Password too short in clean: %s", password)
            self.add_error('password', "Password must be at least 8 characters long.")
        logger.debug("HEMO: Clean completed: %s", cleaned_data)
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
        except Exception as e:
            logger.error("HEMO: Failed to create user %s: %s", username, str(e))
            raise forms.ValidationError(f"Failed to create user: {str(e)}")
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

    class Meta:
        model = Patient
        fields = ['nom', 'prenom', 'cin', 'cnam', 'new_cnam_number', 'entry_date', 'previously_dialysed', 'date_first_dia', 'blood_type']
        widgets = {
            'nom': forms.TextInput(attrs={'placeholder': 'Last Name', 'class': 'form-control'}),
            'prenom': forms.TextInput(attrs={'placeholder': 'First Name', 'class': 'form-control'}),
            'cin': forms.TextInput(attrs={'placeholder': 'CIN', 'class': 'form-control'}),
            'cnam': forms.Select(attrs={'class': 'form-control'}),
            'entry_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'previously_dialysed': forms.CheckboxInput(attrs={'class': 'form-control'}),
            'date_first_dia': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'blood_type': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        self.center = kwargs.pop('center', None)
        super().__init__(*args, **kwargs)
        self.fields['cnam'].queryset = CNAM.objects.all()
        self.fields['cnam'].required = False
        self.fields['blood_type'].choices = Patient.BLOOD_TYPE_CHOICES

    def clean(self):
        cleaned_data = super().clean()
        cnam = cleaned_data.get('cnam')
        new_cnam_number = cleaned_data.get('new_cnam_number')
        previously_dialysed = cleaned_data.get('previously_dialysed')
        date_first_dia = cleaned_data.get('date_first_dia')
        if not cnam and not new_cnam_number:
            self.add_error('new_cnam_number', "Select an existing CNAM number or provide a new one.")
        elif cnam and new_cnam_number:
            self.add_error('new_cnam_number', "Cannot select an existing CNAM and provide a new number.")
        if previously_dialysed and not date_first_dia:
            self.add_error('date_first_dia', "Date of first dialysis is required if previously dialysed.")
        if not previously_dialysed and date_first_dia:
            self.add_error('date_first_dia', "Date of first dialysis should not be set if not previously dialysed.")
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

class HemodialysisSessionForm(forms.ModelForm):
    class Meta:
        model = HemodialysisSession
        fields = ['type', 'method', 'date_of_session', 'responsible_doc']
        widgets = {
            'type': forms.Select(attrs={'class': 'form-control'}),
            'method': forms.Select(attrs={'class': 'form-control'}),
            'date_of_session': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'responsible_doc': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        self.center = kwargs.pop('center', None)
        super().__init__(*args, **kwargs)
        if self.center:
            self.fields['responsible_doc'].queryset = MedicalStaff.objects.filter(center=self.center)
        self.fields['type'].queryset = TypeHemo.objects.all()
        self.fields['method'].queryset = MethodHemo.objects.all()

    def clean(self):
        cleaned_data = super().clean()
        type_hemo = cleaned_data.get('type')
        method = cleaned_data.get('method')
        if type_hemo and method and method.type_hemo != type_hemo:
            self.add_error('method', 'Selected method does not belong to the chosen type.')
        return cleaned_data

class TransmittableDiseaseForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.center = kwargs.pop('center', None)
        super().__init__(*args, **kwargs)

    class Meta:
        model = TransmittableDisease
        fields = ['disease', 'date_of_contraction']
        widgets = {
            'date_of_contraction': forms.DateInput(attrs={'type': 'date'}),
        }

class TransmittableDiseaseRefForm(forms.ModelForm):
    class Meta:
        model = TransmittableDiseaseRef
        fields = ['label_disease', 'type_of_transmission']

class ComplicationsForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.center = kwargs.pop('center', None)
        super().__init__(*args, **kwargs)

    class Meta:
        model = Complications
        fields = ['complication', 'notes', 'date_of_contraction']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 4, 'cols': 50}),
            'date_of_contraction': forms.DateInput(attrs={'type': 'date'}),
        }

class ComplicationsRefForm(forms.ModelForm):
    class Meta:
        model = ComplicationsRef
        fields = ['label_complication']