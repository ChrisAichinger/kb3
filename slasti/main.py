#
# Slasti -- Main Application
#
# Copyright (C) 2011 Pete Zaitcev
# See file COPYING for licensing information (expect GPL 2).
#



import time
import urllib.request, urllib.parse, urllib.error
import difflib
import cgi
import base64
import os
import hashlib
import http.client

# Beautifulsoup 4.x dependency
from bs4 import BeautifulSoup

from slasti import AppError, App400Error, AppLoginError, App404Error
from slasti import AppGetError, AppGetPostError
import slasti
from . import tagbase
import slasti.template

PAGESZ = 25
WHITESTAR = "\u2606"

def list_get_default(lst, index, default=None):
    if index < 0:
        return default
    try:
        return lst[index]
    except IndexError:
        return default

def url_mark(mark, path):
    if mark is None:
        return None
    return '%s/mark.%s' % (path, mark.key_str())

def url_page(mark, path):
    if mark is None:
        return None
    return '%s/page.%s' % (path, mark.key_str())

def url_search(mark, query, path):
    if mark is None:
        return None
    query = slasti.escapeURLComponent(query)
    return '%s/search?q=%s&firstmark=%s' % (path, query, mark.key_str())

def fetch_site_title(url):
    # XXX Seriously, sanitize url before opening the page
    req = urllib.request.urlopen(url)
    content = req.read(10000)
    soup = BeautifulSoup(content)
    return soup.title.text


class Application:
    def __init__(self, basepath, user, db,
                 method, path, query, pinput, cookies,
                 start_response):
        self.basepath = basepath
        self.user = user
        self.base = db
        self.method = method
        self.path = path
        self.query = query
        self.pinput = pinput
        self.cookies = cookies
        self.respond = start_response
        self.userpath = self.basepath + '/' + self.user["name"]

        self.is_logged_in = self.login_verify()

        self.query_args = self._parse_args(self.query)
        self.pinput_args = self._parse_args(self.pinput)

    def get_query_arg(self, argname):
        return self.query_args.get(argname, None)

    def get_pinput_arg(self, argname):
        return self.pinput_args.get(argname, None)

    def find_post_args(self):
        rdic = {}
        for key in ['title', 'href', 'tags', 'extra']:
            rdic[key] = self.get_pinput_arg(key) or ""

        if not rdic["href"] or not rdic["tags"]:
            raise App400Error("The URL and tags are mandatory")

        return rdic


    def _parse_args(self, args):
        if not args:
            return {}

        qdic = {}
        if isinstance(args, bytes):
            args = args.decode("utf-8")
        for key, value in urllib.parse.parse_qs(args).items():
            if isinstance(key, bytes):
                key = key.decode("utf-8", 'replace')
            if isinstance(value[0], bytes):
                value[0] = value[0].decode("utf-8", 'replace')
            qdic[key] = value[0]

        return qdic

    def create_jsondict(self):
        jsondict = {
                    "s_baseurl": self.basepath,
                    "s_userurl": self.userpath,
                    "s_username": self.user["name"],
                   }
        if self.is_logged_in:
            jsondict["show_export"] = True
            jsondict["show_login"] = False
        else:
            jsondict["show_export"] = False
            jsondict["show_login"] = True

            jsondict["href_login"] = self.userpath + '/login'
            if self.path and self.path != "login" and self.path != "edit":
                jsondict["href_login"] += '?savedref=%s' % self.path
        return jsondict

    def process_request(self):
        # Request paths:
        #   ''              -- default list (starting at latest mark)
        #   page.129        -- bookmark list starting at mark #129
        #   mark.129        -- display single mark #129
        #   export.xml      -- delicious-compatible XML
        #   new             -- GET for the form
        #   edit            -- PUT or POST here, GET may have ?query
        #   delete          -- POST
        #   fetchtitle      -- GET with ?query
        #   login           -- GET/POST to obtain a cookie (not snoop-proof)
        #   anime/          -- tag (must have slash)
        #   anime/page.129  -- tag page off this down
        #   moo.xml/        -- tricky tag
        #   page.129/       -- even trickier tag

        auth_force = object()
        auth_none = object()
        auth_redirect = object()
        commands = {
            "login": {
                "GET": (auth_none, self.login_form),
                "POST": (auth_none, self.login_post),
                },
            "new": {
                "GET": (auth_redirect, self.new_form),
                },
            "edit": {
                "GET": (auth_force, self.edit_form),
                "POST": (auth_force, self.edit_post),
                },
            "delete": {
                "POST": (auth_force, self.delete_post),
                },
            "fetchtitle": {
                "GET": (auth_force, self.fetch_get),
                },
            "": {
                "GET": (auth_none, lambda: self.root_generic_html(tag=None)),
                },
            "export.xml": {
                "GET": (auth_force, self.full_mark_xml),
                },
            "tags": {
                "GET": (auth_none, self.full_tag_html),
                },
            "search": {
                "GET": (auth_none, self.full_search_html),
                },
        }
        if self.path in commands:
            if not self.method in commands[self.path]:
                raise AppGetPostError(self.method)

            auth, callback = commands[self.path][self.method]
            if not self.is_logged_in and auth == auth_force:
                raise AppLoginError()
            if not self.is_logged_in and auth == auth_redirect:
                return self.redirect_to_login()

            return callback()

        if "/" in self.path:
            # Trick: by splitting with limit 2 we prevent users from poisoning
            # the tag with slashes. Not that it matters all that much, still...
            tag, page = self.path.split("/", 2)
            if not page:
                return self.root_generic_html(tag)
            if not page.startswith("page."):
                raise App404Error("Not found: " + self.path)
            p = page.split(".", 1)[1]
            return self.page_generic_html(p[1], tag)
        else:
            if self.path.startswith("mark."):
                mark_id = self.path.split('.', 1)[1]
                return self.one_mark_html(mark_id)
            if self.path.startswith("page."):
                mark_id = self.path.split('.', 1)[1]
                return self.page_generic_html(mark_id, tag=None)
            raise App404Error("Not found: " + self.path)

    def login_verify(self):
        if 'pass' not in self.user:
            return False
        if not self.cookies:
            return False
        if 'login' not in self.cookies:
            return False

        (opdata, xhash) = self.cookies['login'].value.split(':')
        (csalt, flags, whenstr) = opdata.split(',')
        try:
            when = int(whenstr)
        except ValueError:
            return False
        now = int(time.time())
        if now < when or when <= now - 3600 * 24 * 14:
            return False
        if flags != '-':
            return False

        coohash = hashlib.sha256()
        hashdata = self.user['pass'] + opdata
        coohash.update(hashdata.encode("utf-8"))
        if coohash.hexdigest() != xhash:
            return False

        return True

    def login_form(self):
        self.respond("200 OK", [('Content-type', 'text/html; charset=utf-8')])
        jsondict = self.create_jsondict()
        jsondict.update({
                "s_action_login": "%s/login" % self.userpath,
                "savedref": self.get_query_arg("savedref"),
                })
        return [slasti.template.render("html_login.html", jsondict)]

    def login_post(self):
        savedref = self.get_pinput_arg("savedref")
        if savedref:
            savedref = savedref.decode("utf-8", 'replace')
            redihref = "%s/%s" % (self.userpath, savedref)
        else:
            redihref = "%s/" % self.userpath;

        password = self.get_pinput_arg("password")
        if not password:
            raise App400Error("bad password tag")

        # We do not require every user to have a password, in order to have
        # archive users or other pseudo-users. They cannot login, even if they
        # fake the login cookies.
        if 'salt' not in self.user:
            raise AppError("User with no salt: " + self.user["name"])
        if 'pass' not in self.user:
            raise AppError("User with no password: " + self.user["name"])

        pwhash = hashlib.md5()
        pwhash.update(self.user['salt'] + password)
        pwstr = pwhash.hexdigest()

        # We operate on a hex of the salted password's digest, to avoid parsing.
        if pwstr != self.user['pass']:
            self.respond("403 Not Permitted",
                         [('Content-type', 'text/plain; charset=utf-8')])
            jsondict = { "output": "403 Not Permitted: Bad Password\r\n" }
            return [slasti.template.render("simple_output.txt", jsondict)]

        csalt = base64.b64encode(os.urandom(6))
        flags = "-"
        nowstr = "%d" % int(time.time())
        opdata = csalt + "," + flags + "," + nowstr

        coohash = hashlib.sha256()
        hashdata = self.user['pass'] + opdata
        coohash.update(hashdata.encode("utf-8"))
        # We use hex instead of base64 because it's easy to test in shell.
        mdstr = coohash.hexdigest()

        response_headers = [('Content-type', 'text/html; charset=utf-8')]
        # Set an RFC 2901 cookie (not RFC 2965).
        response_headers.append(('Set-Cookie', "login=%s:%s" % (opdata, mdstr)))
        response_headers.append(('Location', redihref))
        self.respond("303 See Other", response_headers)

        jsondict = self.create_jsondict()
        jsondict["href_redir"] = self.redihref
        return [slasti.template.render("html_redirect.html", jsondict)]

    def redirect_to_login(self):
        thisref = self.path + '?' + urllib.parse.quote_plus(self.query)
        login_loc = self.userpath + '/login?savedref=' + thisref
        response_headers = [('Content-type', 'text/html; charset=utf-8'),
                            ('Location', login_loc)]
        self.respond("303 See Other", response_headers)

        jsondict = self.create_jsondict()
        jsondict["href_redir"] = login_loc
        return [slasti.template.render("html_redirect.html", jsondict)]

    def find_similar_marks(self, href):
        if not href:
            return []
        href = href.lower().strip()
        user_parsed = urllib.parse.urlsplit(href)

        candidates = []
        for mark in self.base.get_marks():
            markurl = mark.url.lower()
            if href == markurl:
                # exact match
                return [mark]

            mark_parsed = urllib.parse.urlparse(markurl)
            if user_parsed.netloc != mark_parsed.netloc:
                # Different hosts - not our similar
                continue

            r = difflib.SequenceMatcher(None, href, markurl).quick_ratio()
            if r > 0.8:
                candidates.append((r, mark))

        # Use sort key, otherwise we blow up if two ratios are equal
        # (no compare operations defined for marks)
        candidates = sorted(candidates, key=lambda elem: elem[0], reverse=True)
        return [mark for ratio, mark in candidates]

    def new_form(self):
        title = self.get_query_arg('title')
        href = self.get_query_arg('href')
        similar = self.find_similar_marks(href)

        jsondict = self.create_jsondict()
        jsondict.update({
                "mark": tagbase.DBMark(title=title, url=href),
                "current_tag": "[" + WHITESTAR + "]",
                "s_action_edit": self.userpath + '/edit',
                "s_action_delete": None,
                "similar_marks": similar,
            })
        self.respond("200 OK", [('Content-type', 'text/html; charset=utf-8')])
        return [slasti.template.render("html_editform.html", jsondict)]

    def edit_form(self):
        mark_str = self.get_query_arg("mark")
        mark = self.base.lookup(mark_str)
        if not mark:
            raise App400Error("not found: " + mark_str)

        jsondict = self.create_jsondict()
        jsondict.update({
            "mark": mark,
            "current_tag": WHITESTAR,
            "href_current_tag": url_mark(mark, self.userpath),
            "s_action_edit": url_mark(mark, self.userpath),
            "s_action_delete": self.userpath + '/delete',
            })

        self.respond("200 OK", [('Content-type', 'text/html; charset=utf-8')])
        return [slasti.template.render('html_editform.html', jsondict)]

    # The name edit_post() is a bit misleading, because POST to /edit is used
    # to create new marks, not to edit existing ones (see mark_post() for that).
    def edit_post(self):
        argd = self.find_post_args()

        mark_str = self.base.add1(argd['title'], argd['href'], argd['extra'],
                                  tagbase.split_marks(argd['tags']))
        if not mark_str:
            raise App404Error("Could not add bookmark!")

        redihref = '%s/mark.%s' % (self.userpath, mark_str)

        response_headers = [('Content-type', 'text/html; charset=utf-8')]
        response_headers.append(('Location', redihref))
        self.respond("303 See Other", response_headers)

        jsondict = self.create_jsondict()
        jsondict["href_redir"] = redihref
        return [slasti.template.render("html_redirect.html", jsondict)]

    def delete_post(self):
        self.base.delete(self.base.lookup(self.get_pinput_arg("mark")))

        self.respond("200 OK", [('Content-type', 'text/html; charset=utf-8')])
        jsondict = self.create_jsondict()
        return [slasti.template.render("html_delete.html", jsondict)]

    def page_any_html(self, mark_top, mark_list, what,
                      jsondict_extra, linkmaker):

        mark_list = list(mark_list)
        index = mark_list.index(mark_top)
        if index <= 0:
            mark_prev = None
        else:
            mark_prev = mark_list[max(0, index - PAGESZ)]
        mark_next = list_get_default(mark_list, index + PAGESZ, default=None)

        output_marks = mark_list[index : index + PAGESZ]

        self.respond("200 OK", [('Content-type', 'text/html; charset=utf-8')])
        jsondict = self.create_jsondict()
        jsondict.update({
                "current_tag": what,
                "marks": [m for m in output_marks],
                "show_edit": False,

                "href_page_prev": linkmaker(mark_prev),
                "href_page_this": linkmaker(mark_top),
                "href_page_next": linkmaker(mark_next),
                })
        jsondict.update(jsondict_extra)
        return [slasti.template.render('html_mark.html', jsondict)]

    def page_empty_html(self):
        self.respond("200 OK", [('Content-type', 'text/html; charset=utf-8')])
        jsondict = self.create_jsondict()
        jsondict.update({
                    "show_edit": False,
                    "current_tag": "[-]",
                    "marks": [],
                   })
        return [slasti.template.render('html_mark.html', jsondict)]

    # full_mark_html() would be a Netscape bookmarks file, perhaps.
    def full_mark_xml(self):
        if self.method != 'GET':
            raise AppGetError(self.method)

        self.respond("200 OK", [('Content-type', 'text/xml; charset=utf-8')])
        jsondict = self.create_jsondict()
        jsondict["marks"] = self.base.get_marks()
        return [slasti.template.render('xml_export.xml', jsondict)]

    def full_tag_html(self):
        if self.method != 'GET':
            raise AppGetError(self.method)

        self.respond("200 OK", [('Content-type', 'text/html; charset=utf-8')])
        jsondict = self.create_jsondict()
        jsondict["current_tag"] = "tags"
        jsondict["tags"] = self.base.get_tags()
        return [slasti.template.render("html_tags.html", jsondict)]

    def full_search_html(self):
        if self.method != 'GET':
            raise AppGetError(self.method)

        query = self.get_query_arg('q')
        if not query:
            # If q is missing/empty (e.g. search for ""), redirect to homepage
            response_headers = [('Content-type', 'text/html; charset=utf-8'),
                                ('Location', self.userpath)]
            self.respond("303 See Other", response_headers)

            jsondict = self.create_jsondict()
            jsondict["href_redir"] = self.userpath
            return [slasti.template.render("html_redirect.html", jsondict)]

        marks = [m for m in self.base.get_marks() if m.contains(query)]

        mark_str = self.get_query_arg('firstmark')
        if mark_str:
            mark = self.base.lookup(mark_str)
            if not mark:
                raise App404Error("Bookmark not found: " + mark_str)
            if mark not in marks:
                raise App404Error("Bookmark not in results list: " + mark_str)
        else:
            mark = marks[0]

        return self.page_any_html(
                mark, marks,
                what="[ search results ]",
                jsondict_extra={ "val_search": query },
                linkmaker=lambda mark: url_search(mark, query, self.userpath))

    def mark_post(self, mark):
        argd = self.find_post_args()

        tags = tagbase.split_marks(argd['tags'])
        self.base.edit1(mark, argd['title'], argd['href'], argd['extra'], tags)

        # Since the URL stays the same, we eschew 303 here.
        # Just re-read the base entry with a lookup and pretend this was a GET.
        new_mark = self.base.lookup(mark.id)
        if new_mark == None:
            raise App404Error("Mark not found: " + mark)
        return self.mark_get(new_mark)

    def mark_get(self, mark):
        headers = list(self.base.get_headers())
        index = headers.index(mark)
        mark_prev = list_get_default(headers, index - 1, default=None)
        mark_next = list_get_default(headers, index + 1, default=None)

        self.respond("200 OK", [('Content-type', 'text/html; charset=utf-8')])
        jsondict = self.create_jsondict()
        jsondict.update({
                  "marks": [mark],
                  "show_edit": True,
                  "href_page_prev": url_mark(mark_prev, self.userpath),
                  "href_page_this": url_mark(mark, self.userpath),
                  "href_page_next": url_mark(mark_next, self.userpath),
                 })
        return [slasti.template.render("html_mark.html", jsondict)]

    # The server-side indirection requires extreme care to prevent abuse.
    # User may hit us with URLs that point to generated pages, slow servers,..
    # As the last resort, we never work as a generic proxy.
    def fetch_get(self):
        url = self.get_query_arg("url")
        if not url:
            raise App400Error("no query")
        title = fetch_site_title(url)

        self.respond("200 OK", [('Content-type', 'text/plain; charset=utf-8')])
        jsondict = { "output": '%s\r\n' % title }
        return [slasti.template.render("simple_output.txt", jsondict)]

    def one_mark_html(self, mark_str):
        mark = self.base.lookup(mark_str)
        if mark == None:
            raise App404Error("Mark not found: " + mark_str)
        if self.method == 'GET':
            return self.mark_get(mark)
        if self.method == 'POST':
            if not self.is_logged_in:
                raise AppLoginError()
            return self.mark_post(mark)
        raise AppGetPostError(self.method)

    def root_generic_html(self, tag):
        if self.method != 'GET':
            raise AppGetError(self.method)

        if tag:
            marks = list(self.base.get_tag_marks(tag))
            path = self.userpath + '/' + tag
        else:
            marks = list(self.base.get_marks())
            path = self.userpath

        if not marks:
            if tag:
                raise App404Error("Tag page not found: " + tag)
            else:
                return self.page_empty_html()

        return self.page_any_html(
                marks[0], marks, what=tag, jsondict_extra={},
                linkmaker=lambda mark: url_page(mark, path))

    def page_generic_html(self, mark_str, tag):
        if self.method != 'GET':
            raise AppGetError(self.method)

        if tag:
            marks = list(self.base.get_tag_marks(tag))
            path = self.userpath + '/' + tag
        else:
            marks = list(self.base.get_marks())
            path = self.userpath

        mark = self.base.lookup(mark_str)
        if mark not in marks:
            if tag:
                raise App404Error("Tag page not found: " + tag + " / " + mark_str)
            else:
                # We have to have at least one mark to display a page
                raise App404Error("Page not found: " + mark_str)
        return self.page_any_html(
                mark, marks, what=tag, jsondict_extra={},
                linkmaker=lambda mark: url_page(mark, path))

