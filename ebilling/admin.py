from multiprocessing import Event
from django.contrib import admin
from .models import User, Application,EBill,CallBacks
admin.site.register(User)
admin.site.register(Application)
admin.site.register(EBill)
admin.site.register(CallBacks)