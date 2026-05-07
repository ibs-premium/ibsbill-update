from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ebilling', '0001_initial'),
    ]

    operations = [
        # Add idempotency and webhook tracking fields to EBill
        migrations.AddField(
            model_name='ebill',
            name='credited',
            field=models.BooleanField(default=False, verbose_name='Has meter been credited?'),
        ),
        migrations.AddField(
            model_name='ebill',
            name='webhook_url',
            field=models.CharField(
                blank=True, max_length=500, null=True,
                verbose_name='eBilling webhook URL to notify on completion'
            ),
        ),
        migrations.AddField(
            model_name='ebill',
            name='webhook_notified',
            field=models.BooleanField(default=False, verbose_name='Has eBilling been notified via webhook?'),
        ),
        # Fix EBill.app_url max_length (was 30, too short for real URLs)
        migrations.AlterField(
            model_name='ebill',
            name='app_url',
            field=models.CharField(max_length=500),
        ),
        # Fix EBill.app_ip max_length (was 30, IPv6 needs more space)
        migrations.AlterField(
            model_name='ebill',
            name='app_ip',
            field=models.CharField(max_length=50),
        ),
        # Add status field for tracking MTN payment state
        migrations.AddField(
            model_name='ebill',
            name='status',
            field=models.CharField(blank=True, default='PENDING', max_length=50, null=True),
        ),
    ]
