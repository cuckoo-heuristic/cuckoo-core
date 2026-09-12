from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Parameter',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(max_length=64, unique=True)),
                ('value', models.JSONField()),
                ('unit', models.CharField(blank=True, default='', max_length=16)),
                ('value_type', models.CharField(choices=[('int', 'Int'), ('float', 'Float'), ('bool', 'Bool'), ('str', 'Str'), ('json', 'Json')], default='json', max_length=16)),
            ],
        ),
    ]
