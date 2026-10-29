from datetime import datetime, timedelta, date
from django.db import models
from django.utils import timezone
import pytz
import os

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin


class UserManager(BaseUserManager):
    def create_user(self, email, surname, firstname, password=None, **extra_fields):
        if not email:
            raise ValueError("The Email field is required.")
        if not surname:
            raise ValueError("The Surname field is required.")
        if not firstname:
            raise ValueError("The Firstname field is required.")

        email = self.normalize_email(email)
        user = self.model(email=email, surname=surname, firstname=firstname, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, surname, firstname, password=None):
        extra_fields = {'is_admin': True, 'is_superuser': True, 'is_staff': True}
        return self.create_user(email, surname, firstname, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True, max_length=255)
    surname = models.CharField(max_length=255)
    firstname = models.CharField(max_length=255)
    username = models.CharField(max_length=255, default="admin")
    phone = models.CharField(max_length=15, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_admin = models.BooleanField(default=False)
    groups = models.ManyToManyField('auth.Group', related_name='user_set_custom', blank=True)
    user_permissions = models.ManyToManyField('auth.Permission', related_name='user_permissions_custom', blank=True)
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['surname', 'firstname']
    objects = UserManager()

    def __str__(self):
        return f"{self.firstname} {self.surname} ({self.email})"

    def get_full_name(self):
        return f"{self.firstname} {self.surname}"

    def get_short_name(self):
        return self.firstname

    def has_perm(self, perm, obj=None):
        return True

    def has_module_perms(self, app_label):
        return True


class Application(models.Model):
    name = models.CharField(max_length=30, verbose_name='Name of Application')
    url = models.CharField(max_length=255, verbose_name='url of app')
    key = models.CharField(max_length=17)
    ip_address = models.GenericIPAddressField()

    def __str__(self):
        return self.name


class EBill(models.Model):
    app = models.CharField(max_length=30)
    app_key = models.CharField(max_length=30)
    app_ip = models.CharField(max_length=50)
    app_url = models.CharField(max_length=500)
    amount = models.FloatField()
    username = models.CharField(max_length=50)
    token = models.TextField()
    uuid = models.CharField(max_length=255, unique=True)
    device_id = models.CharField(max_length=255, verbose_name='Device Id, e.g. Meter serial number')
    momo_number = models.CharField(max_length=15, blank=True, default='', verbose_name='Payer MoMo number')
    momo_name = models.CharField(max_length=255, blank=True, default='', verbose_name='Payer MoMo name')
    balance_before = models.FloatField(null=False, default=0)
    balance_after = models.FloatField(null=True, blank=True)

    # MTN MoMo request state
    request_sent = models.BooleanField(default=False)
    momo_api_initial_status_code = models.CharField(max_length=50, null=True, blank=True, default='')
    momo_api_initial_message = models.TextField(null=True, blank=True)
    financial_transaction_id = models.CharField(max_length=255, null=True, blank=True, default='')
    status = models.CharField(max_length=50, null=True, blank=True, default='PENDING')

    # Completion tracking
    request_sent = models.BooleanField(default=False)
    transaction_complete = models.BooleanField(default=False)
    request_datetime = models.DateTimeField(auto_now_add=True)
    request_completed_datetime = models.DateTimeField(null=True, blank=True)

    # Idempotency & webhook
    credited = models.BooleanField(default=False, verbose_name='Has meter been credited?')
    webhook_url = models.CharField(max_length=500, null=True, blank=True,
                                   verbose_name='eBilling webhook URL to notify on completion')
    webhook_notified = models.BooleanField(default=False, verbose_name='Has eBilling been notified via webhook?')

    def __str__(self):
        return f"Request from {self.app} | {self.uuid} | {self.request_datetime}"


class CallBacks(models.Model):
    url = models.CharField(max_length=255, verbose_name='URL of app')
    method = models.CharField(max_length=10, verbose_name='HTTP Method')
    headers = models.TextField(blank=True, null=True, verbose_name='Request Headers')
    contents = models.TextField(verbose_name='Raw Request Body')
    query_params = models.TextField(blank=True, null=True, verbose_name='Query Parameters')
    ip_address = models.GenericIPAddressField(verbose_name='Client IP Address')
    user_agent = models.CharField(max_length=512, blank=True, null=True, verbose_name='User-Agent')
    referrer = models.CharField(max_length=512, blank=True, null=True, verbose_name='HTTP Referrer')
    date = models.DateTimeField(auto_now_add=True, verbose_name='Received At')

    def __str__(self):
        return f"Callback from {self.ip_address} at {self.date}"