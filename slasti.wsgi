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
import http.cookies

# CFGUSERS was replaced by  SetEnv slasti.userconf /slasti-users.conf
CFGUSERS = "slasti-users.conf"

# Replaced by  WSGIDaemonProcess slasti python-path=/usr/lib/slasti-mod
# sys.path = sys.path + [ '/usr/lib/slasti-mod' ]
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

def do_file(environ, start_response, fname):
    method = environ['REQUEST_METHOD']
    if method != 'GET':
        raise AppGetError(method)

    start_response("200 OK", [('Content-type', 'text/plain')])
    return [open("slasti/static_files/" + fname).read()]

## Based on James Gardner's environ dump.
#def do_environ(environ, start_response):
#    method = environ['REQUEST_METHOD']
#    if method != 'GET':
#        raise AppGetError(method)
#
#    sorted_keys = environ.keys()
#    sorted_keys.sort()
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

    method = environ['REQUEST_METHOD']
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

    app = slasti.main.Application(pfx, user, base, method, path, q, pinput, c,
                                  start_response)
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
        static_files = ["edit.js", "style.css", "slasti.js", "jquery.js",
                        "showdown.js"]
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
