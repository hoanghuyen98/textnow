from django.db import migrations

PROXY_US = "http://USER580854-zone-custom-region-US-session-26292747-sessTime-180-sessAuto-1:e4bc36@us.rotgb.711proxy.com:10000"


def seed_proxy(apps, schema_editor):
    ProxySetting = apps.get_model('app', 'ProxySetting')
    ProxySetting.objects.update_or_create(pk=1, defaults={"proxy_us": PROXY_US})


def unseed_proxy(apps, schema_editor):
    ProxySetting = apps.get_model('app', 'ProxySetting')
    ProxySetting.objects.filter(pk=1).update(proxy_us="")


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0020_proxy_setting'),
    ]

    operations = [
        migrations.RunPython(seed_proxy, reverse_code=unseed_proxy),
    ]
