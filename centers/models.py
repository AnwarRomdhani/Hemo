from django.db import models

class Center(models.Model):
    sub_domain = models.CharField(max_length=100, unique=True)
    tel = models.IntegerField()
    nom = models.CharField(max_length=100)
    state = models.CharField(max_length=100)  # State where the center is located
    private = models.BooleanField(default=False)  # False = public, True = private
    mail = models.EmailField()  # Center's email address

    def save(self, *args, **kwargs):
        # Ensure subdomain is lowercase and no spaces
        self.sub_domain = self.sub_domain.lower().replace(" ", "-")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.nom} ({self.sub_domain}.localhost:8000)"

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