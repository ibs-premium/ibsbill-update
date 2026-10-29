import secrets
from django import forms
from django.contrib.auth.forms import AuthenticationForm
from .models import Application


class ApplicationForm(forms.ModelForm):
    class Meta:
        model = Application
        fields = ['name', 'url', 'ip_address', 'key']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. ebilling'}),
            'url': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'https://example.com'}),
            'ip_address': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '0.0.0.0'}),
            'key': forms.TextInput(attrs={'class': 'form-control font-monospace'}),
        }
        help_texts = {
            'key': 'Leave blank to generate a new key automatically.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['key'].required = False

    def clean_key(self):
        # 16 hex chars fits the model's max_length of 17
        return self.cleaned_data.get('key') or secrets.token_hex(8)


class StaffAuthenticationForm(AuthenticationForm):
    """Only staff may sign in to the dashboard."""

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_staff:
            raise forms.ValidationError(self.error_messages['invalid_login'], code='invalid_login',
                                        params={'username': self.username_field.verbose_name})
