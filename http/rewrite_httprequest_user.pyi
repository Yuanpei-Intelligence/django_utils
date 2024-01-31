from django.http import HttpRequest as _HttpRequest
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth.models import User

class HttpRequest(_HttpRequest):
    user: 'User | AnonymousUser'
