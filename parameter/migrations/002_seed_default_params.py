from django.db import migrations


def seed_parameter(apps, schema_editor):
    Parameter = apps.get_model("parameter", "Parameter")

    defaults = [
        ("B", 20, "float", "MHz"),
        ("delta2", -114, "float", "dBm"),
        ("Y_v2i", 3.76, "float", ""),
        ("Y_v2v", 1.8, "float", ""),
        ("sigma_v2i", 8, "float", "dB"),
        ("sigma_v2v", 3, "float", "dB"),
        ("h_rsu", 5, "float", "m"),
        ("h_vehicle", 1.5, "float", "m"),
        ("G_rsu", 8, "float", "dBi"),
        ("G_vehicle", 3, "float", "dBi"),
        ("levy_lambda", 1.5, "float", "-"),
        ("p_discard_init", 0.2, "float", "-"),
        ("S", 50, "float", "-"),
        ("k", 1e-25, "float", "-"),
        ("alpha_n", 0.5, "float", "-"),
        ("cell_radius_rsu", 250, "float", "m"),
        ("rec_noi_rsu", 5, "float", "dB"),
        ("rec_noi_vehicle", 9, "float", "dB"),
        ("pmax_vehicle", 23, "float", "dBm"),
        ("pmax_rsu", 30, "float", "dBm"),
        ("fmax_vehicle", 3, "float", "GHz"),
        ("fmax_rsu", 50, "float", "GHz"),
        ("simulate_time", 120, "int", "s"),
        ("taking_task_time", 30, "int", "s"),
    ]

    for key, value, vtype, unit in defaults:
        Parameter.objects.update_or_create(
            key=key,
            defaults={
                "value": value,
                "value_type": vtype,
                "unit": unit,
            },
        )


def unseed_parameter(apps, schema_editor):
    Parameter = apps.get_model("parameter", "Parameter")
    Parameter.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("parameter", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_parameter, unseed_parameter),
    ]
