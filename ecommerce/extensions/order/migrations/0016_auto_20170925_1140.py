# -*- coding: utf-8 -*-
# Generated by Django 1.10.7 on 2017-09-25 11:40
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0015_create_disable_repeat_order_check_switch'),
    ]

    operations = [
        migrations.AddField(
            model_name='historicalline',
            name='history_change_reason',
            field=models.CharField(max_length=100, null=True),
        ),
        migrations.AddField(
            model_name='historicalorder',
            name='history_change_reason',
            field=models.CharField(max_length=100, null=True),
        ),
    ]
