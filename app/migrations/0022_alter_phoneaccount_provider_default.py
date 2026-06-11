from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0021_proxy_setting_seed'),
    ]

    operations = [
        migrations.AlterField(
            model_name='phoneaccount',
            name='provider',
            field=models.CharField(default='textnow', max_length=30),
        ),
    ]
