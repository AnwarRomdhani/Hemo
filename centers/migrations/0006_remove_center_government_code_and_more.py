# Generated by Django 4.2 on 2025-04-27 14:40

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('centers', '0005_alter_delegation_code_alter_governorate_code'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='center',
            name='government_code',
        ),
        migrations.RemoveField(
            model_name='center',
            name='name_delegate',
        ),
        migrations.RemoveField(
            model_name='center',
            name='state',
        ),
        migrations.AddField(
            model_name='center',
            name='delegation',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='centers.delegation'),
        ),
        migrations.AddField(
            model_name='center',
            name='governorate',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='centers.governorate'),
        ),
    ]
