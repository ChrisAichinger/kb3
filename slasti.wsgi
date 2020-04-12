#
# The WSGI wrapper for Slasti
#
# Copyright (C) 2011 Pete Zaitcev
# See file COPYING for licensing information (expect GPL 2).
#

import sys
import os
import email.utils
import http.cookies
import json
import mimetypes
import time

CFGUSERS = "slasti-users.conf"

# Can replace with WSGIDaemonProcess slasti python-path=/usr/lib/slasti-mod
sys.path.append(os.path.dirname(__file__))
import slasti
from slasti import AppError, App404Error, AppGetError


def load_config(userconf, name):
    with open(userconf, 'r') as fp:
        users = json.load(fp)

    if type(users) is not list:
        raise AppError("Configuration is not a list [...]")

    for u in users:
        if type(u) is not dict:
            raise AppError("Configured user is not a dictionary {...}")
        if 'name' not in u:
            raise AppError(f"User with no name")
        if 'database' not in u:
            raise AppError(f"User with no database: {u['name']}")

    users = {u['name']: u for u in users}
    return users.get(name)


def do_root(environ, start_response):
    method = environ['REQUEST_METHOD']
    if method != 'GET':
        raise AppGetError(method)

    # XXX This really needs some kind of a pretty picture.
    start_response("200 OK", [('Content-type', 'text/plain')])
    return ["Slasti: The Anti-Social Bookmarking\r\n",
            "(https://github.com/zaitcev/slasti)\r\n"]

def parse_http_date(httpdate):
    if not httpdate:
        return None

    emaildate = email.utils.parsedate(httpdate)
    if not emaildate:
        # Failed parsing the date
        return None

    # Result: (year, month, day, hour, min, sec)
    return emaildate[:6]

def do_file(environ, start_response, fname):
    method = environ['REQUEST_METHOD']
    if method != 'GET':
        raise AppGetError(method)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    fpath = os.path.join(script_dir, "slasti/" + fname)
    last_modified = time.gmtime(os.stat(fpath).st_mtime)

    # Guess MIME content type from file extension
    ctype = mimetypes.guess_type(fpath)[0]

    # Check for if-modified-since header and answer accordingly
    if_modified_since = environ.get('HTTP_IF_MODIFIED_SINCE', None)
    if_modified_since = parse_http_date(if_modified_since)
    if if_modified_since == last_modified[:6]:
        # Browser has a cached copy which is still up-to-date
        start_response("304 Not Modified", [('Content-type', ctype)])
        return [b'\r\n']

    headers = [('Content-type', ctype)]

    max_age = 30 * 24 * 3600  # 30 days
    expires = time.time() + max_age
    expires_str = time.strftime("%a, %d-%b-%Y %T %Z", time.gmtime(expires))
    headers.append(('Expires', expires_str))

    mod_str = time.strftime("%a, %d-%b-%Y %T %Z", last_modified)
    headers.append(('Last-Modified', mod_str))

    # Enable caching in Firefox when serving over HTTPS
    headers.append(('Cache-control', 'public, max-age={}'.format(max_age)))

    start_response("200 OK", headers)
    return [open(fpath, 'rb').read()]


def do_user(environ, start_response, path):
    # The prefix must be either empty or absolute (no relative or None).
    pfx = environ['SCRIPT_NAME']
    if pfx == None or pfx == "/":
        pfx = ""
    if pfx != "" and pfx[0] != "/":
        pfx = "/"+pfx

    scheme = environ.get('wsgi.url_scheme', 'http')
    method = environ['REQUEST_METHOD']
    host = environ['HTTP_HOST']
    if method == 'POST':
        try:
            clen = int(environ["CONTENT_LENGTH"])
        except (KeyError, ValueError):
            pinput = environ['wsgi.input'].readline()
        else:
            pinput = environ['wsgi.input'].read(clen)
        # Every Unicode-in-Python preso on the Internet says to decode on the
        # border. However, this is actually disastrous, because pinput may be
        # uuencoded. It we decode it here, parse_qs returns a dictionary of
        # unicode strings, which contain split-up UTF-8 bytes, and then we're
        # dead in the water. So, don't do this.
        #if not isinstance(pinput, unicode):
        #    try:
        #        pinput = unicode(pinput, 'utf-8')
        #    except UnicodeDecodeError:
        #        start_response("400 Bad Request",
        #                       [('Content-type', 'text/plain')])
        #        return ["400 Unable to decode UTF-8 in POST\r\n"]
    else:
        pinput = None

    # Query is already split away by the CGI.
    parsed = path.split("/", 2)

    cfgfile = environ.get('slasti.userconf', CFGUSERS)
    user = load_config(cfgfile, parsed[1])
    if user == None:
        raise App404Error("No such user: "+parsed[1])

    base = slasti.tagbase.SlastiDB(user['database'],
                                   stopwords=user.get('stopwords', []),
                                   stopword_languages=user.get('stopword_languages', []),
                                   ignore_hosts_in_search=user.get('ignore_hosts_in_search', []))

    path = parsed[2] if len(parsed) >= 3 else ""
    q = environ.get('QUERY_STRING', None)

    c = http.cookies.SimpleCookie()
    try:
        c.load(environ['HTTP_COOKIE'])
    except http.cookies.CookieError as e:
        start_response("400 Bad Request", [('Content-type', 'text/plain')])
        return ["400 Bad Cookie: " + str(e).encode("utf-8") + "\r\n"]
    except KeyError:
        c = None

    remote_user = environ.get('slasti.logged_in_user') or environ.get('REMOTE_USER')
    app = slasti.main.Application(pfx, user, base, scheme, method, host, path, q, pinput, c,
                                  remote_user, start_response)
    output = app.process_request()

    return output

def application(environ, start_response):
    path = environ['PATH_INFO']
    if path and not isinstance(path, str):
        try:
            path = str(path, 'utf-8')
        except UnicodeDecodeError:
            start_response("400 Bad Request",
                           [('Content-type', 'text/plain')])
            return ["400 Unable to decode UTF-8 in path\r\n"]

    try:
        stripped_path = path.strip(' ').strip('/')
        static_files = [
            "edit.js", "style.css", "slasti.js", "jquery.js", "stmd.js",
            "html4.js", "uri.js", "html-sanitizer.js",
            "OpenLayers/OpenLayers.light.js",
            "OpenLayers/OpenLayers.light.debug.js",
            "OpenLayers/img/cloud-popup-relative.png",
            "OpenLayers/theme/default/style.css",
            ]
        static_files = ['static_files/' + s for s in static_files]
        if not path or path == "/":
            output = do_root(environ, start_response)
        elif stripped_path in static_files:
            output = do_file(environ, start_response, stripped_path)
        #elif path == "/environ":
        #    return do_environ(environ, start_response)
        else:
            output = do_user(environ, start_response, path)

        # The framework blows up if a unicode string leaks into output list.
        safeout = []
        for s in output:
            if isinstance(s, str):
                safeout.append(s.encode("utf-8"))
            else:
                safeout.append(s)
        return safeout

    except AppError as e:
        start_response("500 Internal Error", [('Content-type', 'text/plain')])
        return [str(e).encode("utf-8"), b"\r\n"]
    except slasti.App400Error as e:
        start_response("400 Bad Request", [('Content-type', 'text/plain')])
        return [b"400 Bad Request: ", str(e).encode("utf-8"), b"\r\n"]
    except slasti.AppLoginError as e:
        start_response("403 Not Permitted", [('Content-type', 'text/plain')])
        return [b"403 Not Logged In\r\n"]
    except App404Error as e:
        start_response("404 Not Found", [('Content-type', 'text/plain')])
        return [str(e).encode("utf-8"), b"\r\n"]
    except AppGetError as e:
        start_response("405 Method Not Allowed",
                       [('Content-type', 'text/plain'), ('Allow', 'GET')])
        return [b"405 Method " + str(e).encode("utf-8") + b" not allowed\r\n"]
    except slasti.AppPostError as e:
        start_response("405 Method Not Allowed",
                       [('Content-type', 'text/plain'), ('Allow', 'POST')])
        return [b"405 Method " + str(e).encode("utf-8") + b" not allowed\r\n"]
    except slasti.AppGetPostError as e:
        start_response("405 Method Not Allowed",
                       [('Content-type', 'text/plain'), ('Allow', 'GET, POST')])
        return [b"405 Method " + str(e).encode("utf-8") + b" not allowed\r\n"]

# from wsgi_lineprof.middleware import LineProfilerMiddleware
# from wsgi_lineprof.filters import FilenameFilter, TotalTimeSorter
# application = LineProfilerMiddleware(application, filters=[FilenameFilter(r"main.py|tagbase.py|slasti.wsgi", regex=True), TotalTimeSorter()])
