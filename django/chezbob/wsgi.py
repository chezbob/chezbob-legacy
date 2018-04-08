#!/usr/bin/env python

import os
import sys
sys.path.append("/git/django")
sys.path.append("/git/django/chezbob")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "chezbob.settings")

#import django.core.handlers.wsgi
#application = django.core.handlers.wsgi.WSGIHandler()

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
