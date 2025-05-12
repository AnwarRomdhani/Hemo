from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from centers.models import TechnicalStaff, MedicalStaff, ParamedicalStaff, AdministrativeStaff, WorkerStaff
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Populate user field for existing staff records'

    def handle(self, *args, **options):
        staff_models = [
            (TechnicalStaff, 'technical_profile'),
            (MedicalStaff, 'medical_profile'),
            (ParamedicalStaff, 'paramedical_profile'),
            (AdministrativeStaff, 'administrative_profile'),
            (WorkerStaff, 'worker_profile'),
        ]

        for model, profile_name in staff_models:
            self.stdout.write(f"Processing {model.__name__}...")
            for staff in model.objects.filter(user__isnull=True):
                try:
                    # Generate unique username
                    base_username = f"{staff.nom.lower()}.{staff.prenom.lower()}"
                    username = base_username
                    counter = 1
                    while User.objects.filter(username=username).exists():
                        username = f"{base_username}{counter}"
                        counter += 1

                    # Create user
                    user = User.objects.create_user(
                        username=username,
                        email=f"{username}@example.com",
                        password="defaultpassword123"  # Change this in production
                    )
                    staff.user = user
                    staff.save()
                    self.stdout.write(self.style.SUCCESS(
                        f"Created user {username} for {staff.nom} {staff.prenom} ({model.__name__})"
                    ))
                except Exception as e:
                    logger.error(f"Error processing {staff.nom} {staff.prenom} ({model.__name__}): {str(e)}")
                    self.stdout.write(self.style.ERROR(
                        f"Failed to create user for {staff.nom} {staff.prenom} ({model.__name__}): {str(e)}"
                    ))

        self.stdout.write(self.style.SUCCESS("User population completed."))