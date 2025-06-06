# Generated by Django 4.2 on 2025-05-05 09:54

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('centers', '0015_patient_blood_type_patient_date_first_dia_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='MedicalActivity',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateField()),
                ('patient', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='medical_activity', to='centers.patient')),
            ],
            options={
                'db_table': 'centers_medicalactivity',
            },
        ),
    ]
