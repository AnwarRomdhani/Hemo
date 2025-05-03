from django.db import models

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

    adresse = models.CharField(max_length=200, blank=True)
    sub_domain = models.CharField(max_length=100, unique=True)
    label = models.CharField(max_length=100)
    tel = models.CharField(max_length=20)
    mail = models.EmailField()
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

class TechnicalStaff(Person):
    qualification = models.CharField(max_length=100)

class MedicalStaff(Person):
    cnom = models.CharField(max_length=100)

class ParamedicalStaff(Person):
    qualification = models.CharField(max_length=100)


#============================Machines
class Membrane(models.Model):
    type = models.CharField(max_length=100)

    def __str__(self):
        return self.type

class Filtre(models.Model):
    STERILISATION_CHOICES = [
        ('WATER_STEAM', 'Water Steam'),
        ('GAMMA_RAYS', 'Gamma Rays'),
        ('ETHYLENE_OXIDE', 'Ethylene Oxide'),
    ]
    type = models.CharField(max_length=100)
    sterilisation = models.CharField(max_length=100, blank=True)  # Comma-separated list

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