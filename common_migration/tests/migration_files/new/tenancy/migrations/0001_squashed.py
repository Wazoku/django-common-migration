# -*- coding: utf-8 -*-
from django.db import migrations


class Migration(migrations.Migration):

    replaces = [
        ('tenancy', '0001_initial'),
        ('tenancy', '0002_set'),
        ('tenancy', '0003_automatically_use_the_public_schema'),
        ('tenancy', '0004_remove_public_schema_client_table_hack'),
    ]

    initial = True

    dependencies = [
    ]

    operations = [
    ]
