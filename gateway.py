#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import web

urls = (
    "/i/update",    "i_update",
    "/o/info/",     "o_info",
)

app = web.application(urls, globals())


class Storage(object):

    def __init__(self):
        self._kv = {}

    def set(self, key_tup, val=None):
        self._kv[key_tup] = val

    def get(self):
        return self._kv.get(key_tup)

storage = Storage()


def render_json(data):
    if (isinstance(data, dict) and '_code' not in data) or not isinstance(data, dict):
        data = { '_code': 0, 'data': data }
    web.header('Content-Type','application/json; charset=utf-8')
    data = json.encode(data)
    return data


class i_update:
    def POST(self):
        wi = web.input()
        js = json.decode(wi.get('json'))
        storage.set((js['host'], js['service']), js['data'])
        return render_json('ok')


class o_info:
    def GET(self):
        wi = web.input()
        key = (wi.get('h'), wi.get('s'))
        data = storage.get(key)
        return render_json('data')


wsgi_app = app.wsgifunc()

if __name__ == "__main__":
    app.run()
