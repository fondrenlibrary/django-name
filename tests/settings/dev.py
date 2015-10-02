from .base import *
import os
import ldap
from django_auth_ldap.config import LDAPSearch

INSTALLED_APPS += ['debug_toolbar']

INTERNAL_IPS = (
    '172.17.42.1',
)

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'name',
        'USER': '',
        'PASSWORD': '',
        'HOST': 'mysql',
    }
}

AUTH_LDAP_SERVER_URI="ldaps://"
AUTH_LDAP_BIND_DN="cn=,ou=,dc=,dc="
AUTH_LDAP_BIND_PASSWORD=""
AUTH_LDAP_USER_SEARCH=LDAPSearch("ou=,dc=,dc=",ldap.SCOPE_SUBTREE,"(uid=%(user)s)")

AUTHENTICATION_BACKENDS = (
      'django_auth_ldap.backend.LDAPBackend',
      'django.contrib.auth.backends.ModelBackend',
   )
