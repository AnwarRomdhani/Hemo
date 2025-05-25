"""import os
import django
from django.core.management import call_command

# Set up Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Hemo.settings")
django.setup()

# Dump only the app data from 'centers' into a UTF-8 encoded JSON file
with open("centers_data.json", "w", encoding="utf-8") as f:
    call_command("dumpdata", "centers", indent=2, stdout=f)
"""
import os
import django
from django.core.management import call_command

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Hemo.settings")
django.setup()

with open("auth_data.json", "w", encoding="utf-8") as f:
    call_command("dumpdata", "auth", indent=2, stdout=f)
