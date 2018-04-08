
from collections import MutableMapping

from django.db.models.query import QuerySet
from django.core.serializers import json, serialize
from django.shortcuts import render_to_response
from django.http import HttpResponseRedirect, HttpResponse


class JsonResponse(HttpResponse):
    def __init__(self, data, *args, **kwargs):
        content = None
        if isinstance(data, QuerySet):
            content = serialize('json', data)
        else:
            content = json.dumps(data, indent=2, cls=json.DjangoJSONEncoder,
                                 ensure_ascii=False)
        kwargs['content_type'] = 'application/json'
        super(JsonResponse, self).__init__(content, *args, **kwargs)


class BobMessages(dict, MutableMapping):
    def __init__(self, *args, **kwds):
        self._errors = []
        self._warnings = []
        self._notes = []
        self['errors']    = self._errors
        self['warnings'] = self._warnings
        self['notes'] = self._notes
        super(dict, self).__init__(*args, **kwds)

    def has_errors(self):
        return len(self._errors) > 0

    def error(self, msg):
        self._errors.append(msg)

    def errors(self, msgs):
        self._errors.extend(msgs)

    def warning(self, msg):
        self._warnings.append(msg)

    def note(self, msg):
        self._notes.append(msg)

    def extend(self, dict_extension):
        for key in dict_extension:
            self[key] = dict_extension[key]
        return self


def error(m):
    return render_to_response('chezbob/base.html', m)


def render_json(data):
    return JsonResponse(data=data)


def render_or_error(template, messages):
    if messages.has_errors():
        return error(messages)
    else:
        return render_to_response(template, messages)


def render_bob_messages(messages, content_type='text/html'):
    if content_type == 'text/json':
        return render_json(messages)
    else:
        return render_or_error("chezbob/bob_message.html", messages)


def redirect_or_error(to_url, messages):
    if messages.has_errors():
        return error(messages)
    else:
        return HttpResponseRedirect(to_url)
