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

from . import main, tagbase
