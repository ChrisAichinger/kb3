#
# Slasti -- the main package
#
# Copyright (C) 2011 Pete Zaitcev
# See file COPYING for licensing information (expect GPL 2).
#



import urllib.request, urllib.parse, urllib.error

class AppError(Exception):
    pass
class App400Error(Exception):
    pass
class AppLoginError(Exception):
    pass
class App404Error(Exception):
    pass
class AppGetError(Exception):
    pass
class AppPostError(Exception):
    pass
class AppGetPostError(Exception):
    pass

def escapeURLComponent(s):
    # Turn s into a bytes first, quote_plus blows up otherwise
    return str(urllib.parse.quote_plus(s.encode("utf-8")))

def escapeURL(s):
    # quote_plus() doesn't work as it clobbers the :// portion of the URL
    # Make sure the resulting string is safe to use within HTML attributes.
    # N.B. Mooneyspace.com hates when we reaplace '&' with %26, so don't.
    # On output, the remaining & will be turned into &quot; by the templating
    # engine. No unescaped-entity problems should result here.
    s = s.replace('"', '%22')
    s = s.replace("'", '%27')
    # s = s.replace('&', '%26')
    s = s.replace('<', '%3C')
    s = s.replace('>', '%3E')
    return s

from . import main, tagbase
