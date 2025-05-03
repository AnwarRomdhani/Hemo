import csv
import logging
import re
from django.core.management.base import BaseCommand
from django.db import transaction
from centers.models import Center, Governorate, Delegation

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Import hemodialysis centers from a CSV file'

    def add_arguments(self, parser):
        parser.add_argument('--file', type=str, help='Path to the CSV file', default='merged_hemodialysis_centers.csv')

    def generate_sub_domain(self, label, existing_domains):
        # Clean label to create a valid sub_domain, handling French characters
        replacements = {'é': 'e', 'è': 'e', 'ê': 'e', 'ë': 'e', 'à': 'a', 'â': 'a', 'ä': 'a', 'î': 'i', 'ï': 'i', 'ô': 'o', 'ö': 'o', 'ù': 'u', 'û': 'u', 'ü': 'u', 'ç': 'c'}
        base = label.lower()
        for char, repl in replacements.items():
            base = base.replace(char, repl)
        base = re.sub(r'[^a-z0-9\s-]', '', base).replace(' ', '-').strip('-')
        sub_domain = base
        counter = 1
        while sub_domain in existing_domains:
            sub_domain = f"{base}-{counter}"
            counter += 1
        return sub_domain

    def normalize_header(self, header):
        # Normalize header to match expected format (case-insensitive, strip spaces and BOM)
        return header.strip().upper().replace('\ufeff', '')

    def handle(self, *args, **kwargs):
        file_path = kwargs['file']
        logger.info(f"Starting import of centers from {file_path}")

        # Map TYPE_ETAB to Center.type_center
        TYPE_ETAB_MAPPING = {
            'PV': 'PRIVATE',
            'HU': 'UNIVERSITY',
            'HR': 'REGIONAL',
            'HC': 'CIRCONSCRIPTION',
            'GSB': 'BASIC',
            'CSB': 'BASIC',  # Added for Centre de Santé de Base
        }

        # Valid choices for code_type_hemo and name_type_hemo
        VALID_CODE_TYPE_HEMO = [choice[0] for choice in Center.CODE_TYPE_HEMO_CHOICES]
        VALID_NAME_TYPE_HEMO = [choice[0] for choice in Center.NAME_TYPE_HEMO_CHOICES]

        imported = 0
        skipped = 0
        existing_domains = set(Center.objects.values_list('sub_domain', flat=True))

        try:
            with open(file_path, 'r', encoding='utf-8-sig') as csvfile:
                reader = csv.DictReader(csvfile)
                # Log raw and normalized headers
                logger.info(f"Raw CSV headers: {reader.fieldnames}")
                normalized_headers = {self.normalize_header(h): h for h in reader.fieldnames}
                logger.info(f"Normalized headers: {list(normalized_headers.keys())}")

                # Validate required headers
                required_headers = ['COD_GOUV', 'NOM_GOUV', 'COD_DELEG', 'NOM_DELEG', 'COD_ETAB', 'LIB_ETAB', 'TYPE_ETAB', 'CODE_TYPE_HEMO', 'NOM_TYPE_HEMO', 'ADRESSE']
                missing_headers = [h for h in required_headers if h not in normalized_headers]
                if missing_headers:
                    logger.error(f"Missing required headers: {missing_headers}")
                    self.stdout.write(self.style.ERROR(f"Missing required headers: {missing_headers}"))
                    return

                with transaction.atomic():
                    for row in reader:
                        try:
                            # Access fields using normalized headers
                            cod_gouv = row[normalized_headers['COD_GOUV']]
                            cod_deleg = row[normalized_headers['COD_DELEG']]
                            cod_etab = row[normalized_headers['COD_ETAB']]
                            label = row[normalized_headers['LIB_ETAB']]
                            type_etab = row[normalized_headers['TYPE_ETAB']]
                            code_type_hemo = row[normalized_headers['CODE_TYPE_HEMO']]
                            name_type_hemo = row[normalized_headers['NOM_TYPE_HEMO']]
                            adresse = row[normalized_headers['ADRESSE']] or ''

                            # Validate center_code
                            try:
                                center_code = int(cod_etab)
                            except (ValueError, TypeError):
                                logger.error(f"Invalid center_code '{cod_etab}' for center '{label}'")
                                skipped += 1
                                continue

                            # Map type_center
                            type_center = TYPE_ETAB_MAPPING.get(type_etab, 'PRIVATE')  # Default to PRIVATE if invalid
                            if type_etab not in TYPE_ETAB_MAPPING:
                                logger.warning(f"Unrecognized TYPE_ETAB '{type_etab}' for center '{label}', defaulting to PRIVATE")

                            # Validate code_type_hemo and name_type_hemo
                            code_type_hemo = code_type_hemo if code_type_hemo in VALID_CODE_TYPE_HEMO else ''
                            name_type_hemo = name_type_hemo if name_type_hemo in VALID_NAME_TYPE_HEMO else ''

                            # Look up Governorate
                            try:
                                governorate = Governorate.objects.get(code=int(cod_gouv))
                            except Governorate.DoesNotExist:
                                logger.error(f"Governorate with code '{cod_gouv}' not found for center '{label}'")
                                skipped += 1
                                continue

                            # Look up Delegation (allow None if missing)
                            delegation = None
                            if cod_deleg:
                                try:
                                    delegation = Delegation.objects.get(
                                        code=int(cod_deleg),
                                        governorate=governorate
                                    )
                                except Delegation.DoesNotExist:
                                    logger.warning(f"Delegation with code '{cod_deleg}' not found for governorate '{governorate.name}' for center '{label}', setting delegation to None")

                            # Generate unique sub_domain
                            sub_domain = self.generate_sub_domain(label, existing_domains)
                            existing_domains.add(sub_domain)

                            # Create Center
                            try:
                                center = Center.objects.create(
                                    sub_domain=sub_domain,
                                    label=label,
                                    tel='',  # Placeholder
                                    mail='',  # Placeholder
                                    adresse=adresse,
                                    center_code=center_code,
                                    type_center=type_center,
                                    code_type_hemo=code_type_hemo,
                                    name_type_hemo=name_type_hemo,
                                    governorate=governorate,
                                    delegation=delegation
                                )
                                logger.info(f"Created center '{center.label}' with sub_domain '{center.sub_domain}'")
                                imported += 1
                            except Exception as e:
                                logger.error(f"Failed to create center '{label}': {str(e)}")
                                skipped += 1

                        except KeyError as e:
                            logger.error(f"Missing field {str(e)} in row for center '{row.get(normalized_headers.get('LIB_ETAB', 'LIB_ETAB'), 'unknown')}': {row}")
                            skipped += 1
                        except Exception as e:
                            logger.error(f"Error processing row for center '{row.get(normalized_headers.get('LIB_ETAB', 'LIB_ETAB'), 'unknown')}': {str(e)}")
                            skipped += 1

        except FileNotFoundError:
            logger.error(f"CSV file '{file_path}' not found")
            self.stdout.write(self.style.ERROR(f"File '{file_path}' not found"))
            return
        except Exception as e:
            logger.error(f"Unexpected error during import: {str(e)}")
            self.stdout.write(self.style.ERROR(f"Unexpected error: {str(e)}"))
            return

        self.stdout.write(self.style.SUCCESS(f"Import completed: {imported} centers imported, {skipped} skipped"))
        logger.info(f"Import completed: {imported} centers imported, {skipped} skipped")