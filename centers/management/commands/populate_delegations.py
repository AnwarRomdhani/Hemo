from django.core.management.base import BaseCommand
import pandas as pd
from centers.models import Delegation, Governorate

class Command(BaseCommand):
    help = 'Populates the Delegation model from Gov.xlsx using COD_GOUV to reference Governorate'

    def handle(self, *args, **options):
        # Clear existing Delegation data
        Delegation.objects.all().delete()
        self.stdout.write('Cleared existing Delegation data.')

        # Read the Excel file
        try:
            df = pd.read_excel('Gov.xlsx')
        except FileNotFoundError:
            self.stderr.write('Error: Gov.xlsx file not found. Please ensure it is in the correct directory.')
            return
        except Exception as e:
            self.stderr.write(f'Error reading Gov.xlsx: {str(e)}')
            return

        # Ensure required columns exist
        required_columns = ['COD_GOUV', 'name']
        if not all(col in df.columns for col in required_columns):
            self.stderr.write(f'Error: Excel file must contain columns {required_columns}')
            return

        # Populate delegations
        created_count = 0
        for index, row in df.iterrows():
            try:
                governorate = Governorate.objects.get(code=row['COD_GOUV'])
                delegation, created = Delegation.objects.update_or_create(
                    name=row['name'],
                    governorate=governorate,
                    defaults={'code': row.get('code', None)}  # Optional delegation code, defaults to None if not present
                )
                if created:
                    created_count += 1
            except Governorate.DoesNotExist:
                self.stderr.write(f'Warning: No Governorate found for COD_GOUV {row["COD_GOUV"]} at row {index + 2}. Skipping.')
            except Exception as e:
                self.stderr.write(f'Error processing row {index + 2}: {str(e)}')

        self.stdout.write(f'Successfully populated {created_count} new delegations and updated existing ones.')

        # Verify the data
        delegation_count = Delegation.objects.count()
        self.stdout.write(f'Total delegations in database: {delegation_count}')