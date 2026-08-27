from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from escrow.models import Party, UserProfile
from .models import Module, Permission, Role, UserModuleAccess, UserRole


class ManagedUserCreationForm(UserCreationForm):
    email = forms.EmailField(required=True)
    role = forms.ChoiceField(choices=UserProfile.ROLE_CHOICES)

    class Meta:
        model = User
        fields = ('username', 'email', 'first_name', 'last_name', 'role', 'password1', 'password2')

    def __init__(self, *args, actor=None, **kwargs):
        self.actor = actor
        super().__init__(*args, **kwargs)

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.is_staff = self.cleaned_data['role'] == 'staff'
        if commit:
            user.save()
            party = Party.objects.create(
                id=f'party-{user.username}-{user.pk}',
                displayName=user.get_full_name() or user.username,
                email=user.email,
                role='buyer' if self.cleaned_data['role'] == 'client' else 'seller',
                user=user,
            )
            UserProfile.objects.create(
                user=user,
                role=self.cleaned_data['role'],
                party=party,
            )
        return user


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)
    role = forms.ChoiceField(choices=(('client', 'Client / Buyer'), ('provider', 'Provider / Seller')))

    class Meta:
        model = User
        fields = ('username', 'email', 'first_name', 'last_name', 'role', 'password1', 'password2')

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        if commit:
            user.save()
            UserProfile.objects.create(user=user, role=self.cleaned_data['role'], party=None)
        return user


class RoleForm(forms.ModelForm):
    permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.filter(is_active=True).order_by('module', 'code'),
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )

    class Meta:
        model = Role
        fields = ('name', 'description', 'is_active', 'permissions')

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if not name:
            raise forms.ValidationError('Enter a role name.')
        return name


class PermissionForm(forms.ModelForm):
    module = forms.ModelChoiceField(queryset=Module.objects.filter(is_active=True).order_by('name'))
    name = forms.CharField(required=False, help_text='Leave blank to generate a name from the permission code.')

    class Meta:
        model = Permission
        fields = ('code', 'name', 'description', 'module')

    def clean_code(self):
        code = self.cleaned_data['code'].strip().lower()
        if '.' not in code or len(code.split('.', 1)[0]) < 2:
            raise forms.ValidationError('Use a permission code in the form module.action, for example transactions.create.')
        return code

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get('name') and cleaned_data.get('code'):
            module_code, action = cleaned_data['code'].split('.', 1)
            cleaned_data['name'] = f'{action.replace("_", " ").title()} {module_code.replace("_", " ").title()}'
        return cleaned_data


class UserRolesForm(forms.Form):
    roles = forms.ModelMultipleChoiceField(queryset=Role.objects.filter(is_active=True), widget=forms.CheckboxSelectMultiple, required=False)

    def __init__(self, *args, user=None, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.actor = actor
        self.fields['roles'].queryset = Role.objects.filter(is_active=True).order_by('name')

    def clean_roles(self):
        roles = self.cleaned_data['roles']
        privileged = roles.filter(permissions__code__in=('users.manage', 'roles.manage')).distinct()
        if self.user == self.actor and privileged.exists() and not self.actor.is_superuser:
            raise forms.ValidationError('You cannot assign yourself higher privileges.')
        if roles.filter(name='Admin').exists() and not self.actor.is_superuser:
            raise forms.ValidationError('Only a platform administrator can assign the Admin role.')
        return roles
