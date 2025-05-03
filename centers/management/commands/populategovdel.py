import csv
from django.core.management.base import BaseCommand
from django.db import transaction
from centers.models import Governorate, Delegation 

class Command(BaseCommand):
    help = 'Populates Governorate and Delegation tables from Tunisian governance CSV data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--csv-path',
            type=str,
            default='List-of-Tunisian-Governorates-EN.csv',
            help='Path to the CSV file (default: List-of-Tunisian-Governorates-EN.csv)',
        )

    def handle(self, *args, **options):
        csv_path = options['csv_path']
        
        try:
            with open(csv_path, mode='r', encoding='utf-8-sig') as file:
                reader = csv.DictReader(file, delimiter=';')
                
                with transaction.atomic():
                    governorates_created = 0
                    delegations_created = 0
                    
                    governorate_cache = {}
                    
                    for row in reader:
                        governorate_name = row['Governorate'].strip()
                        delegation_name = row['Delegation'].strip()
                        
                        # Get or create Governorate
                        if governorate_name not in governorate_cache:
                            governorate, created = Governorate.objects.get_or_create(
                                name=governorate_name,
                                defaults={'code': governorate_name[:3].upper()}  # Auto-generate a simple code
                            )
                            governorate_cache[governorate_name] = governorate
                            if created:
                                governorates_created += 1
                                self.stdout.write(f'Created governorate: {governorate_name}')
                        
                        # Create Delegation
                        delegation, created = Delegation.objects.get_or_create(
                            name=delegation_name,
                            governorate=governorate_cache[governorate_name],
                            defaults={'code': f"{governorate_cache[governorate_name].code}-{delegation_name[:3].upper()}"}
                        )
                        if created:
                            delegations_created += 1
                    
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'\nSuccessfully populated database:\n'
                            f'- Governorates created: {governorates_created}\n'
                            f'- Delegations created: {delegations_created}\n'
                            f'Total records: {governorates_created + delegations_created}'
                        )
                    )
        
        except FileNotFoundError:
            self.stdout.write(
                self.style.ERROR(f'\nError: CSV file not found at path "{csv_path}"\n'
                               'Please ensure the file exists or specify path with --csv-path option')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'\nAn error occurred: {str(e)}\n')
            )
