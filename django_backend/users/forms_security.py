from django import forms

from .models import EmailConfiguration


class EmailConfigurationForm(forms.ModelForm):
    password = forms.CharField(required=False, widget=forms.PasswordInput(render_value=False))

    class Meta:
        model = EmailConfiguration
        fields = ('host', 'port', 'username', 'password', 'useTls', 'useSsl', 'fromEmail', 'enabled')
        widgets = {'useTls': forms.CheckboxInput(), 'useSsl': forms.CheckboxInput(), 'enabled': forms.CheckboxInput()}

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('useTls') and cleaned.get('useSsl'):
            raise forms.ValidationError('Use TLS or SSL, not both.')
        if cleaned.get('enabled') and not cleaned.get('host'):
            raise forms.ValidationError('SMTP host is required when email is enabled.')
        return cleaned

    def save(self, commit=True):
        configuration = super().save(commit=False)
        if not self.cleaned_data.get('password') and self.instance.pk:
            configuration.password = self.instance.password
        if commit:
            configuration.save()
        return configuration