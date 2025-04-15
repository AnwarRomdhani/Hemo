from django.db import models

class Center(models.Model):
    sub_domain = models.CharField(max_length=100, unique=True)
    tel = models.IntegerField()
    label = models.CharField(max_length=100)  # Changed from 'nom' to 'label'
    state = models.CharField(max_length=100)
    private = models.BooleanField(default=False)
    mail = models.EmailField()
    
    # Government-related fields
    government_code = models.CharField(max_length=50, blank=True, null=True)
    delegate_code = models.CharField(max_length=50, blank=True, null=True)
    name_delegate = models.CharField(max_length=100, blank=True, null=True)
    
    # Public center specific fields
    type_center = models.CharField(max_length=100, blank=True, null=True)
    code_type_hemo = models.CharField(max_length=50, blank=True, null=True)
    name_type_hemo = models.CharField(max_length=100, blank=True, null=True)

    def save(self, *args, **kwargs):
        self.sub_domain = self.sub_domain.lower().replace(" ", "-")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.label} ({self.sub_domain}.localhost:8000)"

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