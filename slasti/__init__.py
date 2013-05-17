#
# Slasti -- the main package
#
# Copyright (C) 2011 Pete Zaitcev
# See file COPYING for licensing information (expect GPL 2).
#

from __future__ import unicode_literals

import urllib
import urlparse

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

def safestr(u):
    if isinstance(u, unicode):
        return u.encode('utf-8')
    return u

def escapeURLComponent(s):
    # Turn s into a bytes first, quote_plus blows up otherwise
    return unicode(urllib.quote_plus(s.encode("utf-8")))

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

import main, tagbase
