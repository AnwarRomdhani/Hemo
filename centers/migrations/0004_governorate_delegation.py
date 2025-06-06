# Generated by Django 4.2 on 2025-04-27 13:09

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('centers', '0003_rename_nom_center_label_center_code_type_hemo_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='Governorate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True)),
                ('code', models.CharField(blank=True, max_length=10, null=True)),
            ],
        ),
        migrations.CreateModel(
            name='Delegation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('code', models.CharField(blank=True, max_length=10, null=True)),
                ('governorate', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='delegations', to='centers.governorate')),
            ],
            options={
                'unique_together': {('name', 'governorate')},
            },
        ),
    ]
