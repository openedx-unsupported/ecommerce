# Generated by Django 2.2.14 on 2020-07-23 16:04

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('basket', '0013_auto_20200305_1448'),
    ]

    operations = [
        migrations.AddField(
            model_name='line',
            name='date_updated',
            field=models.DateTimeField(auto_now=True, db_index=True, verbose_name='Date Updated'),
        ),
    ]
