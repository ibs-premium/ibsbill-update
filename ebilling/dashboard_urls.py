from django.contrib.auth import views as auth_views
from django.urls import path
from . import dashboard
from .forms import StaffAuthenticationForm

app_name = 'dashboard'

urlpatterns = [
    path('login/', auth_views.LoginView.as_view(template_name='dashboard/login.html',
                                                authentication_form=StaffAuthenticationForm,
                                                redirect_authenticated_user=True), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='dashboard:login'), name='logout'),
    path('', dashboard.overview, name='overview'),
    path('pay/', dashboard.pay, name='pay'),
    path('reports/', dashboard.reports, name='reports'),
    path('transactions/', dashboard.transactions, name='transactions'),
    path('transactions/check/', dashboard.transactions_check, name='transactions_check'),
    path('transactions/<int:pk>/', dashboard.transaction_detail, name='transaction_detail'),
    path('transactions/<int:pk>/check/', dashboard.transaction_check, name='transaction_check'),
    path('applications/', dashboard.applications, name='applications'),
    path('applications/<int:pk>/edit/', dashboard.application_edit, name='application_edit'),
    path('applications/<int:pk>/delete/', dashboard.application_delete, name='application_delete'),
    path('callbacks/', dashboard.callbacks, name='callbacks'),
    path('callbacks/<int:pk>/', dashboard.callback_detail, name='callback_detail'),
]
