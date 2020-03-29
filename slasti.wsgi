#
# The WSGI wrapper for Slasti
#
# Copyright (C) 2011 Pete Zaitcev
# See file COPYING for licensing information (expect GPL 2).
#

import string
import json
import types
import sys
import os
import http.cookies
import email.utils
import time
import mimetypes

# CFGUSERS was replaced by  SetEnv slasti.userconf /slasti-users.conf
CFGUSERS = "slasti-users.conf"

# Can replace with WSGIDaemonProcess slasti python-path=/usr/lib/slasti-mod
sys.path.append(os.path.dirname(__file__))
import slasti
from slasti import AppError, App404Error, AppGetError

# The idea here is the same as with the file-backed tags database:
# something simple to implement but with an API that presumes a higher
# performance implementation later, if necessary.
class UserBase:
    def __init__(self):
        self.users = None

    def open(self, userconf):
        try:
            fp = open(userconf, 'r')
        except IOError as e:
            raise AppError(str(e))

        try:
            self.users = json.load(fp)
        except ValueError as e:
            raise AppError(str(e))

        fp.close()

        # In order to prevent weird tracebacks later, we introspect and make
        # sure that configuration makes sense structurally and that correct
        # fields are present. Using helpful ideas by Andrew "Pixy" Maizels.

        if not (type(self.users) is list):
            raise AppError("Configuration is not a list [...]")

        for u in self.users:
            if not (type(u) is dict):
                raise AppError("Configured user is not a dictionary {...}")

            if 'name' not in u:
                raise AppError("User with no name")
            if 'type' not in u:
                raise AppError("User with no type: "+u['name'])
            # Check 'root' for type 'fs' only in the future.
            if 'root' not in u:
                raise AppError("User with no root: "+u['name'])

    def lookup(self, name):
        if self.users == None:
            return None
        for u in self.users:
            if u['name'] == name:
                return u
        return None

    def close(self):
        pass
    # This has to be implemented when close() becomes non-empty, due to
    # the way AppError bubbles up and bypasses the level where we close.
    #def __del__(self):
    #    pass

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

## Based on James Gardner's environ dump.
#def do_environ(environ, start_response):
#    method = environ['REQUEST_METHOD']
#    if method != 'GET':
#        raise AppGetError(method)
#
#    sorted_keys = sorted(environ.keys())
#
#    response_headers = [('Content-type', 'text/html')]
#    start_response("200 OK", response_headers)
#    output = ["<html><body><h1><kbd>environ</kbd></h1><p>"]
#
#    for kval in sorted_keys:
#        output.append("<br />")
#        output.append(kval)
#        output.append("=")
#        output.append(str(environ[kval]))
#
#    output.append("</p></body></html>")
#
#    return output

def do_user(environ, start_response, path):
    # We will stop reloading UserBase on every call once we figure out how.
    users = UserBase()
    if 'slasti.userconf' not in environ:
        environ['slasti.userconf'] = CFGUSERS
    if 'slasti.userconf' not in environ:
        raise AppError("No environ 'slasti.userconf'")
    users.open(environ['slasti.userconf'])

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

    user = users.lookup(parsed[1])
    if user == None:
        raise App404Error("No such user: "+parsed[1])
    if user['type'] != 'fs':
        raise AppError("Unknown type of user: "+parsed[1])

    if len(parsed) >= 3:
        path = parsed[2]
    else:
        path = ""

    try:
        q = environ['QUERY_STRING']
    except KeyError:
        q = None

    c = http.cookies.SimpleCookie()
    try:
        c.load(environ['HTTP_COOKIE'])
    except http.cookies.CookieError as e:
        start_response("400 Bad Request", [('Content-type', 'text/plain')])
        return ["400 Bad Cookie: " + str(e).encode("utf-8") + "\r\n"]
    except KeyError:
        c = None

    base = slasti.tagbase.SlastiDB(user['root'])

    remote_user = environ.get('slasti.logged_in_user') or \
                  environ.get('REMOTE_USER')
    app = slasti.main.Application(pfx, user, base, scheme, method, host, path, q, pinput, c,
                                  remote_user, start_response)
    output = app.process_request()

    return output

def application(environ, start_response):

    # import os, pwd
    # os.environ["HOME"] = pwd.getpwuid(os.getuid()).pw_dir

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

# We do not have __main__ in WSGI.
# if __name__.startswith('_mod_wsgi_'):
#    ...
