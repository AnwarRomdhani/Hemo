import logging
from django.db import models
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
logger = logging.getLogger(__name__)

class Center(models.Model):
    CENTER_TYPES = [
        ('CIRCONSCRIPTION', 'Circonscription Hospital'),
        ('REGIONAL', 'Regional Hospital'),
        ('UNIVERSITY', 'University Hospital'),
        ('BASIC', 'Basic health group'),
        ('PRIVATE', 'Private'),
    ]
    CODE_TYPE_HEMO_CHOICES = [
        ('MD2200', 'MD2200'),
        ('UNITE', 'UNITE'),
        ('UNITEP', 'UNITEP'),
    ]
    NAME_TYPE_HEMO_CHOICES = [
        ('SERVICE HEMODIALYSE', 'SERVICE HEMODIALYSE'),
        ('UNITE HEMODIALYSE', 'UNITE HEMODIALYSE'),
        ('UNITE HEMODIALYSE PEDIATRIQUE', 'UNITE HEMODIALYSE PEDIATRIQUE'),
    ]

    sub_domain = models.CharField(max_length=100, unique=True)
    label = models.CharField(max_length=100)
    tel = models.CharField(max_length=20, blank=True)
    mail = models.EmailField(blank=True)
    adresse = models.CharField(max_length=200, blank=True)
    governorate = models.ForeignKey("Governorate", on_delete=models.CASCADE, null=True)
    delegation = models.ForeignKey("Delegation", on_delete=models.CASCADE, null=True, blank=True)
    type_center = models.CharField(max_length=20, choices=CENTER_TYPES, blank=False)
    code_type_hemo = models.CharField(max_length=10, choices=CODE_TYPE_HEMO_CHOICES, blank=True)
    name_type_hemo = models.CharField(max_length=30, choices=NAME_TYPE_HEMO_CHOICES, blank=True)
    center_code = models.IntegerField(null=True)

    def save(self, *args, **kwargs):
        self.sub_domain = self.sub_domain.lower().replace(" ", "-")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.label} ({self.sub_domain}.localhost:8000)"

class Governorate(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.IntegerField(null=True, blank=True)
    
    def __str__(self):
        return f"{self.name} ({self.code})"

class Delegation(models.Model):
    name = models.CharField(max_length=100)
    governorate = models.ForeignKey(Governorate, on_delete=models.CASCADE, related_name='delegations')
    code = models.IntegerField(null=True, blank=True)
    
    class Meta:
        unique_together = ('name', 'governorate')
    
    def __str__(self):
        return f"{self.name} ({self.code})"

class Person(models.Model):
    nom = models.CharField(max_length=100)
    prenom = models.CharField(max_length=100)
    cin = models.CharField(max_length=50, unique=True)
    center = models.ForeignKey(Center, on_delete=models.CASCADE, related_name='%(class)s_staff')

    class Meta:
        abstract = True

    def __str__(self):
        return f"{self.nom} {self.prenom} ({self.cin})"

class AdministrativeStaff(models.Model):
    ROLE_CHOICES = [
        ('LOCAL_ADMIN', 'Local Admin'),
        ('SUBMITTER', 'Submitter'),
        ('MEDICAL_PARA_STAFF', 'Medical & Paramedical Staff'),
        ('VIEWER', 'Viewer'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='administrative_profile', null=False, blank=False)
    nom = models.CharField(max_length=100)
    prenom = models.CharField(max_length=100)
    cin = models.CharField(max_length=50, unique=True)
    center = models.ForeignKey(Center, on_delete=models.CASCADE, related_name='administrative_staff')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='VIEWER')
    job_title = models.CharField(max_length=100)  # E.g., Secretary, Manager

    class Meta:
        db_table = 'centers_administrativestaff'

    def __str__(self):
        return f"{self.nom} {self.prenom} ({self.cin})"

class MedicalStaff(models.Model):
    ROLE_CHOICES = [
        ('LOCAL_ADMIN', 'Local Admin'),
        ('SUBMITTER', 'Submitter'),
        ('MEDICAL_PARA_STAFF', 'Medical & Paramedical Staff'),
        ('VIEWER', 'Viewer'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='medical_profile', null=False, blank=False)
    nom = models.CharField(max_length=100)
    prenom = models.CharField(max_length=100)
    cin = models.CharField(max_length=50, unique=True)
    center = models.ForeignKey(Center, on_delete=models.CASCADE, related_name='medical_staff')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='MEDICAL_PARA_STAFF')
    cnom = models.CharField(max_length=100)

    class Meta:
        db_table = 'centers_medicalstaff'

    def __str__(self):
        return f"{self.nom} {self.prenom} ({self.cin})"

class ParamedicalStaff(models.Model):
    ROLE_CHOICES = [
        ('LOCAL_ADMIN', 'Local Admin'),
        ('SUBMITTER', 'Submitter'),
        ('MEDICAL_PARA_STAFF', 'Medical & Paramedical Staff'),
        ('VIEWER', 'Viewer'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='paramedical_profile', null=False, blank=False)
    nom = models.CharField(max_length=100)
    prenom = models.CharField(max_length=100)
    cin = models.CharField(max_length=50, unique=True)
    center = models.ForeignKey(Center, on_delete=models.CASCADE, related_name='paramedical_staff')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='MEDICAL_PARA_STAFF')
    qualification = models.CharField(max_length=100)

    class Meta:
        db_table = 'centers_paramedicalstaff'

    def __str__(self):
        return f"{self.nom} {self.prenom} ({self.cin})"

class TechnicalStaff(models.Model):
    ROLE_CHOICES = [
        ('LOCAL_ADMIN', 'Local Admin'),
        ('SUBMITTER', 'Submitter'),
        ('MEDICAL_PARA_STAFF', 'Medical & Paramedical Staff'),
        ('VIEWER', 'Viewer'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='technical_profile', null=False, blank=False)
    nom = models.CharField(max_length=100)
    prenom = models.CharField(max_length=100)
    cin = models.CharField(max_length=50, unique=True)
    center = models.ForeignKey(Center, on_delete=models.CASCADE, related_name='technical_staff')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='VIEWER')
    qualification = models.CharField(max_length=100)

    class Meta:
        db_table = 'centers_technicalstaff'

    def __str__(self):
        return f"{self.nom} {self.prenom} ({self.cin})"

class WorkerStaff(models.Model):
    ROLE_CHOICES = [
        ('LOCAL_ADMIN', 'Local Admin'),
        ('SUBMITTER', 'Submitter'),
        ('MEDICAL_PARA_STAFF', 'Medical & Paramedical Staff'),
        ('VIEWER', 'Viewer'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='worker_profile', null=False, blank=False)
    nom = models.CharField(max_length=100)
    prenom = models.CharField(max_length=100)
    cin = models.CharField(max_length=50, unique=True)
    center = models.ForeignKey(Center, on_delete=models.CASCADE, related_name='worker_staff')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='VIEWER')
    job_title = models.CharField(max_length=100)  # E.g., Janitor, Technician

    class Meta:
        db_table = 'centers_workerstaff'

    def __str__(self):
        return f"{self.nom} {self.prenom} ({self.cin})"

class CNAM(models.Model):
    number = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.number

    class Meta:
        db_table = 'centers_cnam'

class Patient(Person):
    BLOOD_TYPE_CHOICES = [
        ('A+', 'A+'),
        ('A-', 'A-'),
        ('B+', 'B+'),
        ('B-', 'B-'),
        ('AB+', 'AB+'),
        ('AB-', 'AB-'),
        ('O+', 'O+'),
        ('O-', 'O-'),
    ]
    
    cnam = models.ForeignKey(CNAM, on_delete=models.CASCADE, related_name='patients')
    status = models.CharField(max_length=20, default='Active')
    entry_date = models.DateField()
    previously_dialysed = models.BooleanField(default=False)
    date_first_dia = models.DateField(null=True, blank=True)
    blood_type = models.CharField(max_length=3, choices=BLOOD_TYPE_CHOICES)

    class Meta:
        db_table = 'centers_patient'

    def clean(self):
        if self.previously_dialysed and not self.date_first_dia:
            raise ValidationError({'date_first_dia': 'Date of first dialysis is required if previously dialysed.'})
        if not self.previously_dialysed and self.date_first_dia:
            raise ValidationError({'date_first_dia': 'Date of first dialysis should not be set if not previously dialysed.'})

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new:
            try:
                MedicalActivity.objects.create(
                    patient=self,
                    created_at=self.entry_date
                )
                logger.info("Created MedicalActivity for new patient %s", self)
            except Exception as e:
                logger.error("Failed to create MedicalActivity for patient %s: %s", self, str(e))
                raise

class MedicalActivity(models.Model):
    patient = models.OneToOneField(Patient, on_delete=models.CASCADE, related_name='medical_activity')
    created_at = models.DateField()
    class Meta:
        db_table = 'centers_medicalactivity'

class Membrane(models.Model):
    type = models.CharField(max_length=100)

    def __str__(self):
        return self.type

class Filtre(models.Model):
    STERILISATION_CHOICES = [
        ('WATER_STEAM', 'Water Steam'),
        ('GAMMA_RAYS', 'Gamma Rays'),
        ('ETH ethylene_OXIDE', 'Ethylene Oxide'),
    ]
    type = models.CharField(max_length=100)
    sterilisation = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return self.type

class Machine(models.Model):
    center = models.ForeignKey(Center, on_delete=models.CASCADE, related_name='machines')
    brand = models.CharField(max_length=100)
    functional = models.BooleanField(default=True)
    reserve = models.BooleanField(default=False)
    refurbished = models.BooleanField(default=False)
    nbre_hrs = models.IntegerField(default=0)
    membrane = models.ForeignKey(Membrane, on_delete=models.CASCADE)
    filtre = models.ForeignKey(Filtre, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.brand} ({self.center.label})"
    
class TypeHemo(models.Model):
    name = models.CharField(max_length=50, unique=True)

    class Meta:
        db_table = 'centers_typehemo'

    def __str__(self):
        return self.name

class MethodHemo(models.Model):
    type_hemo = models.ForeignKey(TypeHemo, on_delete=models.CASCADE, related_name='methods')
    name = models.CharField(max_length=50)

    class Meta:
        db_table = 'centers_methodhemo'
        unique_together = ('type_hemo', 'name')

    def __str__(self):
        return f"{self.name} ({self.type_hemo.name})"

class TransmittableDiseaseRef(models.Model):
    label_disease = models.CharField(max_length=100, unique=True)
    type_of_transmission = models.CharField(max_length=50)

    class Meta:
        db_table = 'centers_transmittablediseaseref'

    def __str__(self):
        return f"{self.label_disease} ({self.type_of_transmission})"

class TransmittableDisease(models.Model):
    medical_activity = models.ForeignKey(MedicalActivity, on_delete=models.CASCADE, related_name='transmittable_diseases')
    disease = models.ForeignKey(TransmittableDiseaseRef, on_delete=models.CASCADE)
    date_of_contraction = models.DateField()

    class Meta:
        db_table = 'centers_transmittabledisease'

    def __str__(self):
        return f"{self.disease.label_disease} for {self.medical_activity.patient} on {self.date_of_contraction}"

class ComplicationsRef(models.Model):
    label_complication = models.CharField(max_length=100, unique=True)

    class Meta:
        db_table = 'centers_complicationsref'

    def __str__(self):
        return self.label_complication

class Complications(models.Model):
    medical_activity = models.ForeignKey(MedicalActivity, on_delete=models.CASCADE, related_name='complications')
    complication = models.ForeignKey(ComplicationsRef, on_delete=models.CASCADE)
    notes = models.TextField(blank=True)
    date_of_contraction = models.DateField()

    class Meta:
        db_table = 'centers_complications'

    def __str__(self):
        return f"{self.complication.label_complication} for {self.medical_activity.patient} on {self.date_of_contraction}"

class HemodialysisSession(models.Model):
    medical_activity = models.ForeignKey(MedicalActivity, on_delete=models.CASCADE, related_name='hemodialysis_sessions')
    type = models.ForeignKey(TypeHemo, on_delete=models.CASCADE)
    method = models.ForeignKey(MethodHemo, on_delete=models.CASCADE)
    date_of_session = models.DateField()
    responsible_doc = models.ForeignKey(MedicalStaff, on_delete=models.CASCADE)

    class Meta:
        db_table = 'centers_hemodialysissession'

    def clean(self):
        if self.method.type_hemo != self.type:
            raise ValidationError({'method': 'Selected method does not belong to the chosen type.'})

    def __str__(self):
        return f"{self.type.name} Session for {self.medical_activity.patient} on {self.date_of_session}"