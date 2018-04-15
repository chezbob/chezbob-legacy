#!/bin/bash
export PYTHONPATH=/git/django
#export DJANGO_SETTINGS_MODULE=chezbob.settings
. /git/django/env/bin/activate
$@
