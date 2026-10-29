from django.urls import path
from django.views.generic import RedirectView
from . import views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('', RedirectView.as_view(pattern_name='dashboard:overview'), name='index'),
    # eBilling initiates a payment request
    path('bill/', views.bill, name='bill'),
    # MTN MoMo posts final payment result here
    path('bill/mtn-callback/', views.mtn_callback, name='mtn_callback'),
    # eBilling polls here to check if payment is complete
    path('bill/callback/', views.bill_status, name='bill_status'),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)