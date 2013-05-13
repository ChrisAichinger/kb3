#
# Slasti -- Main Application
#
# Copyright (C) 2011 Pete Zaitcev
# See file COPYING for licensing information (expect GPL 2).
#

from __future__ import unicode_literals

import time
import urllib
import urlparse
import difflib
import cgi
import base64
import os
import hashlib
import httplib
# XXX sgmllib was removed in Python 3.0
import sgmllib

from slasti import AppError, App400Error, AppLoginError, App404Error
from slasti import AppGetError, AppGetPostError
import slasti
import tagbase
import slasti.template

PAGESZ = 25
WHITESTAR = "\u2606"

def page_back(mark):
    mark = mark.pred()
    if mark == None:
        return None
    # In all other cases, we'll return something, even if 1 entry back.
    n = 1
    while n < PAGESZ:
        m = mark.pred()
        if m == None:
            return mark
        mark = m
        n += 1
    return mark

def page_url_from_mark(mark, path):
    if mark is None:
        return None
    return '%s/page.%s' % (path, mark.key_str())

def search_back(mark_top, query):
    mark = mark_top.pred()
    if not mark:
        return None
    n = 0
    while True:
        # Search for PAGESZ+1 matches, then call call succ() on the first one.
        # This avoids showing the "previous page" link on the first page when
        # doing a search, clicking ">> next page", followed by "<< prev page".
        # Otherwise we'd show a previous page button, even if there's no
        # matches in earlier bookmarks.
        if mark.contains(query):
            n += 1
        if n > PAGESZ:
            return mark.succ()

        mark_pred = mark.pred()
        if not mark_pred:
            return mark
        mark = mark_pred

def search_url_from_mark(mark, query, path):
    if mark is None:
        return None
    mark_str = mark.key_str()
    query = slasti.escapeURLComponent(query)
    return '%s/search?q=%s&firstmark=%s' % (path, query, mark_str)

def find_post_args(ctx):
    rdic = {}
    for key in ['title', 'href', 'tags', 'extra']:
        rdic[key] = ctx.get_pinput_arg(key) or ""

    if not rdic["href"] or not rdic["tags"]:
        raise App400Error("The URL and tags are mandatory")

    return rdic

def page_any_html(start_response, ctx, mark_top):
    what = mark_top.tag()

    if what:
        path = ctx.userpath + '/' + what
    else:
        path = ctx.userpath

    start_response("200 OK", [('Content-type', 'text/html; charset=utf-8')])
    jsondict = ctx.create_jsondict()
    jsondict["current_tag"] = what
    jsondict["marks"] = []

    mark = mark_top
    mark_next = None
    n = 0
    for n in range(PAGESZ):
        jsondict["marks"].append(mark.to_jsondict(ctx.userpath))

        mark_next = mark.succ()
        if mark_next == None:
            break
        mark = mark_next

    jsondict.update({
            "href_page_prev": page_url_from_mark(page_back(mark_top), path),
            "href_page_this": page_url_from_mark(mark_top, path),
            "href_page_next": page_url_from_mark(mark_next, path),
            })
    return [slasti.template.template_html_page.substitute(jsondict)]

def page_mark_html(start_response, ctx, mark_str):
    mark = ctx.base.lookup(mark_str)
    if mark == None:
        # We have to have at least one mark to display a page
        raise App404Error("Page not found: " + mark_str)
    if ctx.method != 'GET':
        raise AppGetError(ctx.method)
    return page_any_html(start_response, ctx, mark)

def page_tag_html(start_response, ctx, tag, mark_str):
    mark = ctx.base.lookup(mark_str)
    mark = ctx.base.taglookup(tag, mark)
    if mark == None:
        raise App404Error("Tag page not found: " + tag + " / " + mark_str)
    if ctx.method != 'GET':
        raise AppGetError(ctx.method)
    return page_any_html(start_response, ctx, mark)

def page_empty_html(start_response, ctx):
    start_response("200 OK", [('Content-type', 'text/html; charset=utf-8')])
    jsondict = ctx.create_jsondict()
    jsondict.update({
                "current_tag": "[-]",
                "marks": [],
               })
    return [slasti.template.template_html_page.substitute(jsondict)]

def delete_post(start_response, ctx):
    ctx.base.delete(ctx.base.lookup(ctx.get_pinput_arg("mark")))

    start_response("200 OK", [('Content-type', 'text/html; charset=utf-8')])
    jsondict = ctx.create_jsondict()
    return [slasti.template.template_html_delete.substitute(jsondict)]

class FetchParser(sgmllib.SGMLParser):
    def __init__(self, verbose=0):
        sgmllib.SGMLParser.__init__(self, verbose)
        self.in_title = False
        self.titlestr = None
    def start_title(self, attributes):
        self.in_title = True
    def end_title(self):
        self.in_title = False
    def handle_data(self, data):
        if self.in_title:
            self.titlestr = data

def fetch_parse(chunk):
    parser = FetchParser()
    parser.feed(chunk)
    parser.close()
    if parser.titlestr == None:
        return "(none)"
    return parser.titlestr

# XXX This may need switching to urllib yet, if 301 redirects become a problem.
def fetch_body(url):
    # XXX Seriously, sanitize url before parsing

    scheme, host, path, u_par, u_query, u_frag = urlparse.urlparse(url)
    if scheme != 'http' and scheme != 'https':
        raise App400Error("bad url scheme")

    headers = {}
    # XXX Forward the Referer: that we received from the client, if any.

    if scheme == 'http':
        conn = httplib.HTTPConnection(host, timeout=25)
    else:
        conn = httplib.HTTPSConnection(host, timeout=25)

    conn.request("GET", path, None, headers)
    response = conn.getresponse()
    # XXX A different return code for 201 and 204?
    if response.status != 200:
        raise App400Error("target error %d" % response.status)

    typeval = response.getheader("Content-Type")
    if typeval == None:
        raise App400Error("target no type")
    typestr = typeval.split(";")
    if len(typestr) == 0:
        raise App400Error("target type none")
    if typestr[0] != 'text/html':
        raise App400Error("target type %s" % typestr[0])

    body = response.read(10000)
    return body

#
# The server-side indirection requires extreme care to prevent abuse.
# User may hit us with URLs that point to generated pages, slow servers, etc.
# As the last resort, we never work as a generic proxy.
#
def fetch_get(start_response, ctx):
    url = ctx.get_query_arg("url")
    if not url:
        raise App400Error("no query")
    body = fetch_body(url)
    title = fetch_parse(body)

    start_response("200 OK", [('Content-type', 'text/plain; charset=utf-8')])
    jsondict = { "output": '%s\r\n' % title }
    return [slasti.template.template_simple_output.substitute(jsondict)]

def mark_post(start_response, ctx, mark):
    argd = find_post_args(ctx)

    tags = tagbase.split_marks(argd['tags'])
    ctx.base.edit1(mark, argd['title'], argd['href'], argd['extra'], tags)

    # Since the URL stays the same, we eschew 303 here.
    # Just re-read the base entry with a lookup and pretend this was a GET.
    new_mark = ctx.base.lookup(mark.key_str())
    if new_mark == None:
        raise App404Error("Mark not found: " + mark)
    return mark_get(start_response, ctx, new_mark)

def mark_get(start_response, ctx, mark):
    start_response("200 OK", [('Content-type', 'text/html; charset=utf-8')])
    jsondict = ctx.create_jsondict()
    jsondict.update({
              "marks": [mark.to_jsondict(ctx.userpath)],
              "href_edit": mark.get_editpath(ctx.userpath),
              "href_page_prev": page_url_from_mark(mark.pred(), ctx.userpath),
              "href_page_this": page_url_from_mark(mark, ctx.userpath),
              "href_page_next": page_url_from_mark(mark.succ(), ctx.userpath),
             })
    return [slasti.template.template_html_mark.substitute(jsondict)]

def one_mark_html(start_response, ctx, mark_str):
    mark = ctx.base.lookup(mark_str)
    if mark == None:
        raise App404Error("Mark not found: " + mark_str)
    if ctx.method == 'GET':
        return mark_get(start_response, ctx, mark)
    if ctx.method == 'POST':
        if ctx.flogin == 0:
            raise AppLoginError()
        return mark_post(start_response, ctx, mark)
    raise AppGetPostError(ctx.method)

def root_mark_html(start_response, ctx):
    if ctx.method != 'GET':
        raise AppGetError(ctx.method)
    mark = ctx.base.first()
    if mark == None:
        return page_empty_html(start_response, ctx)
    return page_any_html(start_response, ctx, mark)
    ## The non-paginated version
    #
    # response_headers = [('Content-type', 'text/html')]
    # start_response("200 OK", response_headers)
    # output = ["<html><body>\n"]
    #
    # left_lead = '  <h2 style="margin-bottom:0">'+\
    #             '<a href="%s/">%s</a></h2>\n' % \
    #             (ctx.path, ctx.user['name']))
    # spit_lead(output, ctx, left_lead)
    #
    # for mark in base:
    #     (stamp0, stamp1) = mark.key()
    #     datestr = time.strftime("%Y-%m-%d", time.gmtime(stamp0))
    #
    #     output.append("<p>%s %s " % \
    #                   (datestr, mark_anchor_html(mark, ctx.path, WHITESTAR)))
    #     output.append(mark.html())
    #     output.append("</p>\n")
    #
    # output.append("</body></html>\n")
    # return output

def root_tag_html(start_response, ctx, tag):
    mark = ctx.base.tagfirst(tag)
    if mark == None:
        # Not sure if this may happen legitimately, so 404 for now.
        raise App404Error("Tag page not found: " + tag)
    if ctx.method != 'GET':
        raise AppGetError(ctx.method)
    return page_any_html(start_response, ctx, mark)

# full_mark_html() would be a Netscape bookmarks file, perhaps.
def full_mark_xml(start_response, ctx):
    if ctx.method != 'GET':
        raise AppGetError(ctx.method)

    start_response("200 OK", [('Content-type', 'text/xml; charset=utf-8')])
    jsondict = { "marks": [], "name_user": ctx.user['name'] }
    for mark in ctx.base:
        jsondict["marks"].append(mark.to_jsondict(ctx.userpath))

    return [slasti.template.template_xml_export.substitute(jsondict)]

def full_tag_html(start_response, ctx):
    if ctx.method != 'GET':
        raise AppGetError(ctx.method)

    start_response("200 OK", [('Content-type', 'text/html; charset=utf-8')])
    jsondict = ctx.create_jsondict()
    jsondict["current_tag"] = "tags"
    jsondict["tags"] = []
    for tag in ctx.base.tagcurs():
        ref = tag.key()
        jsondict["tags"].append(
            {"href_tag": '%s/%s/' % (ctx.userpath,
                                     slasti.escapeURLComponent(ref)),
             "name_tag": ref,
             "num_tagged": tag.num(),
            })
    return [slasti.template.template_html_tags.substitute(jsondict)]

def full_search_html(start_response, ctx):
    if ctx.method != 'GET':
        raise AppGetError(ctx.method)

    query = ctx.get_query_arg('q')
    if not query:
        # If q is missing/empty (e.g. search for ""), redirect to homepage
        response_headers = [('Content-type', 'text/html; charset=utf-8'),
                            ('Location', slasti.safestr(ctx.userpath))]
        start_response("303 See Other", response_headers)

        jsondict = { "href_redir": ctx.userpath }
        return [slasti.template.template_html_redirect.substitute(jsondict)]

    firstmark = ctx.get_query_arg('firstmark')
    if not firstmark:
        mark_top = ctx.base.first()
    else:
        mark_top = ctx.base.lookup(firstmark)
        if not mark_top:
            raise App400Error("not found: " + firstmark)

    start_response("200 OK", [('Content-type', 'text/html; charset=utf-8')])
    jsondict = ctx.create_jsondict()
    jsondict["current_tag"] = "[ search results ]"
    jsondict["val_search"] = query

    mark = mark_top
    markslist = []
    while mark and len(markslist) < PAGESZ:
        if mark.contains(query):
            markslist.append(mark.to_jsondict(ctx.userpath))

        mark = mark.succ()

    mark_prev = search_back(mark_top, query)
    jsondict.update({
            "marks": markslist,
            "href_page_prev": search_url_from_mark(mark_prev, query,
                                                   ctx.userpath),
            "href_page_this": search_url_from_mark(mark_top, query,
                                                   ctx.userpath),
            "href_page_next": search_url_from_mark(mark, query, ctx.userpath),
            })
    return [slasti.template.template_html_page.substitute(jsondict)]

def login_form(start_response, ctx):
    start_response("200 OK", [('Content-type', 'text/html; charset=utf-8')])
    jsondict = {
            "username": ctx.user['name'],
            "action_login": "%s/login" % ctx.userpath,
            "savedref": ctx.get_query_arg("savedref"),
            }
    return [slasti.template.template_html_login.substitute(jsondict)]

def login_post(start_response, ctx):

    # pinput = "password=test&OK=Enter" and possibly a newline
    savedref = ctx.get_pinput_arg("savedref")
    if savedref:
        savedref = savedref.decode("utf-8", 'replace')
        redihref = "%s/%s" % (ctx.userpath, savedref)
    else:
        redihref = "%s/" % ctx.userpath;

    password = ctx.get_pinput_arg("password")
    if not password:
        raise App400Error("bad password tag")

    # We do not require every user to have a password, in order to have
    # archive users or other pseudo-users. They cannot login, even if they
    # fake the login cookies.
    if not ctx.user.has_key('salt'):
        raise AppError("User with no salt: " + ctx.user["name"])
    if not ctx.user.has_key('pass'):
        raise AppError("User with no password: " + ctx.user["name"])

    pwhash = hashlib.md5()
    pwhash.update(ctx.user['salt'] + password)
    pwstr = pwhash.hexdigest()

    # We operate on a hex of the salted password's digest, to avoid parsing.
    if pwstr != ctx.user['pass']:
        start_response("403 Not Permitted",
                       [('Content-type', 'text/plain; charset=utf-8')])
        jsondict = { "output": "403 Not Permitted: Bad Password\r\n" }
        return [slasti.template.template_simple_output.substitute(jsondict)]

    csalt = base64.b64encode(os.urandom(6))
    flags = "-"
    nowstr = "%d" % int(time.time())
    opdata = csalt + "," + flags + "," + nowstr

    coohash = hashlib.sha256()
    coohash.update(ctx.user['pass'] + opdata)
    # We use hex instead of base64 because it's easy to test in shell.
    mdstr = coohash.hexdigest()

    response_headers = [('Content-type', 'text/html; charset=utf-8')]
    # Set an RFC 2901 cookie (not RFC 2965).
    response_headers.append(('Set-Cookie', "login=%s:%s" % (opdata, mdstr)))
    response_headers.append(('Location', slasti.safestr(redihref)))
    start_response("303 See Other", response_headers)

    jsondict = { "href_redir": redihref }
    return [slasti.template.template_html_redirect.substitute(jsondict)]

def login(start_response, ctx):
    if ctx.method == 'GET':
        return login_form(start_response, ctx)
    if ctx.method == 'POST':
        return login_post(start_response, ctx)
    raise AppGetPostError(ctx.method)

def login_verify(ctx):
    if not ctx.user.has_key('pass'):
        return 0
    if ctx.cookies == None:
        return 0
    if not ctx.cookies.has_key('login'):
        return 0

    cval = ctx.cookies['login'].value
    (opdata, xhash) = cval.split(':')
    (csalt,flags,whenstr) = opdata.split(',')
    try:
        when = int(whenstr)
    except ValueError:
        return 0
    now = int(time.time())
    if now < when or now >= when + 1209600:
        return 0
    if flags != '-':
        return 0

    coohash = hashlib.sha256()
    coohash.update(ctx.user['pass'] + opdata)
    mdstr = coohash.hexdigest()

    if mdstr != xhash:
        return 0

    return 1

def find_similar_marks(href, ctx):
    if not href:
        return []
    href = href.lower().strip()
    user_parsed = urlparse.urlsplit(href)

    candidates = []
    mark = ctx.base.first()
    while mark:
        markurl = mark.url.lower()
        if href == markurl:
            # exact match
            return [mark]

        mark_parsed = urlparse.urlparse(markurl)
        if user_parsed.netloc != mark_parsed.netloc:
            # Different hosts - not our similar
            mark = mark.succ()
            continue

        r = difflib.SequenceMatcher(None, href, markurl).quick_ratio()
        if r > 0.8:
            candidates.append((r, mark))

        mark = mark.succ()

    # Use sort key, otherwise we blow up if two ratios are equal
    # (no compare operations defined for marks)
    candidates = sorted(candidates, key=lambda elem: elem[0], reverse=True)
    return [mark for ratio, mark in candidates]

def new_form(start_response, ctx):
    title = ctx.get_query_arg('title')
    href = ctx.get_query_arg('href')
    similar = find_similar_marks(href, ctx)

    jsondict = ctx.create_jsondict()
    jsondict.update({
            "id_title": "title1",
            "id_button": "button1",
            "href_editjs": ctx.prefix + '/edit.js',
            "href_fetch": ctx.userpath + '/fetchtitle',
            "mark": None,
            "current_tag": "[" + WHITESTAR + "]",
            "action_edit": ctx.userpath + '/edit',
            "val_title": title,
            "val_href": href,
            "similar_marks": [m.to_jsondict(ctx.userpath) for m in similar],
        })
    start_response("200 OK", [('Content-type', 'text/html; charset=utf-8')])
    return [slasti.template.template_html_editform.substitute(jsondict)]

def edit_form(start_response, ctx):
    mark_str = ctx.get_query_arg("mark")
    mark = ctx.base.lookup(mark_str)
    if not mark:
        raise App400Error("not found: " + mark_str)

    jsondict = ctx.create_jsondict()
    jsondict.update({
        "id_title": "title1",
        "id_button": "button1",
        "href_editjs": ctx.prefix + '/edit.js',
        "href_fetch": ctx.userpath + '/fetchtitle',
        "mark": mark.to_jsondict(ctx.userpath),
        "current_tag": WHITESTAR,
        "href_current_tag": '%s/mark.%s' % (ctx.userpath, mark.key_str()),
        "action_edit": "%s/mark.%s" % (ctx.userpath, mark.key_str()),
        "action_delete": ctx.userpath + '/delete',
        "val_title": mark.title,
        "val_href": mark.url,
        "val_tags": ' '.join(mark.tags),
        "val_note": mark.note,
        })

    start_response("200 OK", [('Content-type', 'text/html; charset=utf-8')])
    return [slasti.template.template_html_editform.substitute(jsondict)]

# The name edit_post() is a bit misleading, because POST to /edit is used
# to create new marks, not to edit existing ones (see mark_post() for that).
def edit_post(start_response, ctx):
    argd = find_post_args(ctx)
    tags = tagbase.split_marks(argd['tags'])

    mark_str = ctx.base.add1(argd['title'], argd['href'], argd['extra'], tags)
    if not mark_str:
        raise App404Error("Out of fix")

    redihref = '%s/mark.%s' % (ctx.userpath, mark_str)

    response_headers = [('Content-type', 'text/html; charset=utf-8')]
    response_headers.append(('Location', slasti.safestr(redihref)))
    start_response("303 See Other", response_headers)

    jsondict = { "href_redir": redihref }
    return [slasti.template.template_html_redirect.substitute(jsondict)]

def new(start_response, ctx):
    if ctx.method == 'GET':
        return new_form(start_response, ctx)
    raise AppGetError(ctx.method)

def edit(start_response, ctx):
    if ctx.method == 'GET':
        return edit_form(start_response, ctx)
    if ctx.method == 'POST':
        return edit_post(start_response, ctx)
    raise AppGetPostError(ctx.method)

def delete(start_response, ctx):
    if ctx.method == 'POST':
        return delete_post(start_response, ctx)
    raise AppPostError(ctx.method)

def fetch_title(start_response, ctx):
    if ctx.method == 'GET':
        return fetch_get(start_response, ctx)
    raise AppGetError(ctx.method)

def redirect_to_login(start_response, ctx):
    thisref = ctx.path + '?' + urllib.quote_plus(ctx._query)
    login_loc = ctx.userpath + '/login?savedref=' + thisref
    response_headers = [('Content-type', 'text/html; charset=utf-8'),
                        ('Location', slasti.safestr(login_loc))]
    start_response("303 See Other", response_headers)

    jsondict = { "href_redir": login_loc }
    return [slasti.template.template_html_redirect.substitute(jsondict)]

#
# Request paths:
#   ''                  -- default index (page.XXXX.XX)
#   page.1296951840.00  -- page off this down
#   mark.1296951840.00
#   export.xml          -- del-compatible XML
#   new                 -- GET for the form
#   edit                -- PUT or POST here, GET may have ?query
#   delete              -- POST
#   fetchtitle          -- GET with ?query
#   login               -- GET or POST to obtain a cookie (not snoop-proof)
#   anime/              -- tag (must have slash)
#   anime/page.1293667202.11  -- tag page off this down
#   moo.xml/            -- tricky tag
#   page.1293667202.11/ -- even trickier tag
#
def app(start_response, ctx):
    ctx.flogin = login_verify(ctx)

    if ctx.path == "login":
        return login(start_response, ctx)
    if ctx.path == "new":
        if ctx.flogin == 0:
            return redirect_to_login(start_response, ctx)
        return new(start_response, ctx)
    if ctx.path == "edit":
        if ctx.flogin == 0:
            raise AppLoginError()
        return edit(start_response, ctx)
    if ctx.path == "delete":
        if ctx.flogin == 0:
            raise AppLoginError()
        return delete(start_response, ctx)
    if ctx.path == "fetchtitle":
        if ctx.flogin == 0:
            raise AppLoginError()
        return fetch_title(start_response, ctx)
    if ctx.path == "":
        return root_mark_html(start_response, ctx)
    if ctx.path == "export.xml":
        if ctx.flogin == 0:
            raise AppLoginError()
        return full_mark_xml(start_response, ctx)
    if ctx.path == "tags":
        return full_tag_html(start_response, ctx)
    if ctx.path == "search":
        return full_search_html(start_response, ctx)
    if "/" in ctx.path:
        # Trick: by splitting with limit 2 we prevent users from poisoning
        # the tag with slashes. Not that it matters all that much, but still.
        p = ctx.path.split("/", 2)
        tag = p[0]
        page = p[1]
        if page == "":
            return root_tag_html(start_response, ctx, tag)
        p = page.split(".", 1)
        if len(p) != 2:
            raise App404Error("Not found: " + ctx.path)
        if p[0] != "page":
            raise App404Error("Not found: " + ctx.path)
        return page_tag_html(start_response, ctx, tag, p[1])
    else:
        p = ctx.path.split(".", 1)
        if len(p) != 2:
            raise App404Error("Not found: " + ctx.path)
        mark_str = p[1]
        if p[0] == "mark":
            return one_mark_html(start_response, ctx, mark_str)
        if p[0] == "page":
            return page_mark_html(start_response, ctx, mark_str)
        raise App404Error("Not found: " + ctx.path)
