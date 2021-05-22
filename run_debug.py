#!/usr/bin/python3

from werkzeug.wsgi import DispatcherMiddleware
from kb3 import create_app


def simple(env, resp):
    resp(b'200 OK', [(b'Content-Type', b'text/plain')])
    return [b'Hello WSGI World']

app = create_app()
app.config['DEBUG'] = True
app.wsgi_app = DispatcherMiddleware(simple, {app.config['APPLICATION_ROOT']: app.wsgi_app})

if __name__ == '__main__':
    app.run('localhost', 5000)
