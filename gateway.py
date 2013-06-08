#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import web

urls = (
    "/i/update",    "i_update",
    "/o/info",     "o_info",
    "/o/view",     "o_view",
)

app = web.application(urls, globals())


class Storage(object):

    def __init__(self):
        self._kv = {}

    def set(self, key_tup, val=None):
        self._kv[key_tup] = val

    def get(self, key_tup):
        return self._kv.get(key_tup)

    def to_json(self):
        m = {}
        for k, v in self._kv.iteritems():
            m['%s|%s' % k] = v
        return m

storage = Storage()


def render_json(data):
    if (isinstance(data, dict) and '_code' not in data) or not isinstance(data, dict):
        data = { '_code': 0, 'data': data }
    web.header('Content-Type','application/json; charset=utf-8')
    data = json.dumps(data)
    return data


class i_update:
    def POST(self):
        wi = web.input()
        js = json.loads(wi.get('json'))
        for l in js['list']:
            storage.set((js['host'], l['service']), l['data'])
        return render_json('ok')


class o_info:
    def GET(self):
        wi = web.input()
        key = (wi.get('h'), wi.get('s'))
        data = storage.get(key)
        data.update({
            'mem': 0,
            'cpu': 0,
        })
        segs = ['<pre>\n']
        for k, v in data.iteritems():
            segs.append('%s:%s\n' % (k, v))
        segs.append('</pre>\n')
        web.header('Content-Type','text/plain; charset=utf-8')
        return ''.join(segs)


class o_view:
    def GET(self):
        return render_json(storage.to_json())


wsgi_app = app.wsgifunc()

if __name__ == "__main__":
    app.run()
