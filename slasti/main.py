#
# Slasti -- Main Application
#
# Copyright (C) 2011 Pete Zaitcev
# See file COPYING for licensing information (expect GPL 2).
#



import sys
import os
import re
import time
import urllib.request, urllib.parse, urllib.error
import base64
import hashlib

from nltk.corpus import stopwords as nltk_stopwords

import slasti
import slasti.template
from slasti import AppError, App400Error, AppLoginError, App404Error
from slasti import AppGetError, AppGetPostError

from . import tagbase

PAGESZ = 60
WHITESTAR = "\u2606"


def b64encode(string):
    return base64.b64encode(string.encode("utf-8"), b'-_').decode()

def b64decode(b64string):
    if isinstance(b64string, str):
        b64string = b64string.encode("utf-8")
    try:
        return base64.b64decode(b64string, b'-_', validate=True).decode("utf-8")
    except (base64.binascii.Error, UnicodeDecodeError, TypeError):
        return ""

def b64validate(b64string):
    if not b64string or not b64decode(b64string):
        return ""
    return b64string


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


class SearchStrParser:
    class ParsingError(RuntimeError):
        explanation = property(lambda self: self.args[0])

    class Sentinel:
        pass

    class Operator(Sentinel):
        pass

    class TopLevelOperator(Operator):
        precedence = 0

    class Not(Operator):
        valence = 1
        precedence = 3
        associativity = "right"
        op = staticmethod(lambda lhs: not lhs)

    class And(Operator):
        valence = 2
        precedence = 2
        associativity = "left"
        op = staticmethod(lambda lhs, rhs: lhs and rhs)

    class Or(Operator):
        valence = 2
        precedence = 1
        associativity = "left"
        op = staticmethod(lambda lhs, rhs: lhs or rhs)

    class POpen(Sentinel):
        pass

    class PClose(Sentinel):
        pass

    class ParserStr(str):
        valence = 0
        pass

    def __init__(self, query):
        self.full_query = query
        self.tokenize()
        self.tokens_to_rpn()
        self.validate_rpn()

    def add_token(self, token, consume=0):
        if not isinstance(token, SearchStrParser.Sentinel):
            # Convert str to ParserStr, so we can add arbitrary attributes.
            token = SearchStrParser.ParserStr(token)
        token.pos = len(self.full_query) - len(self.s)
        self.tokens.append(token)
        self.s = self.s[consume:]

    def error_on_token(self, message, token):
        raise SearchStrParser.ParsingError(
                "{}:\n{}\n{}\u2191".format(message, self.full_query,
                                           " " * token.pos))

    def tokenize(self):
        self.s = self.full_query
        self.tokens = []
        while True:
            self.s = self.s.lstrip()
            if not self.s:
                return

            if self.s[0] in "\"'":
                try:
                    end_quote = self.s[1:].index(self.s[0]) + 1
                except ValueError:
                    # Quoted string is not terminated in search string,
                    # so we simply ignore the quote.
                    self.s = self.s[1:]
                    continue
                self.add_token(self.s[1:end_quote], consume=end_quote + 1)

            elif self.s[0] == '!':
                self.add_token(SearchStrParser.Not(), consume=1)
            elif self.s[0] == '&':
                self.add_token(SearchStrParser.And(), consume=1)
            elif self.s[0] == '|':
                self.add_token(SearchStrParser.Or(), consume=1)
            elif self.s[0] == '(':
                self.add_token(SearchStrParser.POpen(), consume=1)
            elif self.s[0] == ')':
                self.add_token(SearchStrParser.PClose(), consume=1)
            else:
                m = re.search(r'\s|[!&|"\'()]', self.s)
                if not m:
                    # The current token stretches till the end of the input.
                    self.add_token(self.s, consume=len(self.s))
                else:
                    # A normal token.
                    self.add_token(self.s[:m.start()], consume=m.start())

    def tokens_to_rpn(self):
        # Create a new token list with "And" tokens inserted between all other
        # tokens except next to already present operators.
        tokens = []
        for i in range(len(self.tokens)):
            tokens.append(self.tokens[i])
            if i + 1 >= len(self.tokens):
                continue

            token_this = self.tokens[i]
            token_next = self.tokens[i + 1]
            if (    not isinstance(token_this, SearchStrParser.Operator) and
                    not isinstance(token_next, SearchStrParser.Operator) and
                    not isinstance(token_this, SearchStrParser.POpen) and
                    not isinstance(token_next, SearchStrParser.PClose)):
                and_op = SearchStrParser.And()
                and_op.pos = token_next.pos
                tokens.append(and_op)

        output = []
        op_stack = [SearchStrParser.TopLevelOperator]
        while tokens:
            token = tokens.pop(0)
            if isinstance(token, SearchStrParser.ParserStr):
                output.append(token)
            elif isinstance(token, SearchStrParser.Operator):
                while (isinstance(op_stack[-1], SearchStrParser.Operator) and
                       ((token.associativity == "left" and
                         token.precedence <= op_stack[-1].precedence)
                       or
                        token.precedence < op_stack[-1].precedence
                       )):
                    output.append(op_stack.pop())
                op_stack.append(token)
            elif isinstance(token, SearchStrParser.POpen):
                op_stack.append(token)
            elif isinstance(token, SearchStrParser.PClose):
                if not op_stack:
                    self.error_on_token("Unmatched close paren", token)
                while not isinstance(op_stack[-1], SearchStrParser.POpen):
                    output.append(op_stack.pop())
                    if not op_stack:
                        self.error_on_token("Unmatched close paren", token)
                op_stack.pop()
            else:
                raise NotImplementedError("Something gone wrong")

        while op_stack:
            token = op_stack.pop()
            if isinstance(token, SearchStrParser.POpen):
                self.error_on_token("Unmatched open paren", token)
            output.append(token)

        # Remove the trailing TopLevelOperator.
        output.pop()

        self.rpn = output
        return self.rpn

    def validate_rpn(self):
        stack_size = 0
        for token in self.rpn:
            stack_size += 1 - token.valence
            if stack_size <= 0:
                self.error_on_token("Syntax error around token", token)
        if stack_size != 1:
            raise SearchStrParser.ParsingError("Unknown syntax error")

    def evaluate(self, callback):
        stack = []
        for token in self.rpn:
            if isinstance(token, SearchStrParser.Operator):
                args = [stack.pop() for i in range(token.valence)]
                stack.append(token.op(*args))
            else:
                stack.append(callback(token))

        # Syntax errors should be cought in validate_rpn(), however, keep this
        # check here so we don't accidently hide a bug.
        if len(stack) != 1:
            raise RuntimeError("Stack gone wrong: " + repr(stack))
        return stack[0]


class Application:
    def __init__(self, basepath, user, db,
                 scheme, method, path, query, pinput, cookies, remote_user,
                 start_response):
        self.basepath = basepath
        self.user = user
        self.base = db
        self.scheme = scheme
        self.method = method
        self.path = path
        self.query = query
        self.pinput = pinput
        self.cookies = cookies
        self.remote_user = remote_user
        self.respond = start_response
        self.userpath = self.basepath + '/' + self.user["name"]
        self.staticpath = self.basepath + '/static_files'

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
                    "s_staticurl": self.staticpath,
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
                savedref = b64encode(self.path)
                jsondict["href_login"] += '?savedref=%s' % savedref
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
        if self.user.get('private', False) and not self.is_logged_in:
            if self.path != 'login':
                if self.method == 'GET':
                    return self.redirect_to_login()
                raise AppLoginError()

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
            return self.page_generic_html(p, tag)
        else:
            if self.path.startswith("mark."):
                mark_id = self.path.split('.', 1)[1]
                return self.one_mark_html(mark_id)
            if self.path.startswith("page."):
                mark_id = self.path.split('.', 1)[1]
                return self.page_generic_html(mark_id, tag=None)
            raise App404Error("Not found: " + self.path)

    def login_verify(self):
        if self.user.get("serverauth", False):
            # HTTP Auth / Server based auth is enabled for the user.
            if self.remote_user == self.user["name"]:
               return True
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
                "savedref": b64validate(self.get_query_arg("savedref")),
                })
        return [slasti.template.render("html_login.html", jsondict)]

    def login_post(self):
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
        pwhash.update((self.user['salt'] + password).encode("utf-8"))
        pwstr = pwhash.hexdigest()

        # We operate on a hex of the salted password's digest, to avoid parsing.
        if pwstr != self.user['pass']:
            self.respond("403 Not Permitted",
                         [('Content-type', 'text/plain; charset=utf-8')])
            jsondict = { "output": "403 Not Permitted: Bad Password\r\n" }
            return [slasti.template.render("simple_output.txt", jsondict)]

        csalt = base64.b64encode(os.urandom(6)).decode("utf-8")
        flags = "-"
        nowstr = "%d" % int(time.time())
        opdata = csalt + "," + flags + "," + nowstr

        coohash = hashlib.sha256()
        hashdata = self.user['pass'] + opdata
        coohash.update(hashdata.encode("utf-8"))
        # We use hex instead of base64 because it's easy to test in shell.
        mdstr = coohash.hexdigest()

        savedref = b64decode(self.get_pinput_arg("savedref"))
        if savedref:
            redihref = "%s/%s" % (self.userpath, savedref)
        else:
            redihref = "%s/" % self.userpath

        response_headers = [('Content-type', 'text/html; charset=utf-8')]
        # Set an RFC 2901 cookie (not RFC 2965).
        cookie = ["login=%s:%s" % (opdata, mdstr), "HttpOnly"]
        if self.scheme.lower() == 'https':
            cookie.append("Secure")
        response_headers.append(('Set-Cookie', '; '.join(cookie)))
        response_headers.append(('Location', redihref))
        self.respond("303 See Other", response_headers)

        jsondict = self.create_jsondict()
        jsondict["us_redirect"] = redihref
        return [slasti.template.render("html_redirect.html", jsondict)]

    def redirect_to_login(self):
        savedref = self.path + '?' + self.query
        login_loc = self.userpath + '/login?savedref=' + b64encode(savedref)
        response_headers = [('Content-type', 'text/html; charset=utf-8'),
                            ('Location', login_loc)]
        self.respond("303 See Other", response_headers)

        jsondict = self.create_jsondict()
        jsondict["us_redirect"] = login_loc
        return [slasti.template.render("html_redirect.html", jsondict)]

    def new_form(self):
        title = self.get_query_arg('title')
        url = self.get_query_arg('href') or ''
        mark = tagbase.DBMark(title=title, url=url)
        return self._edit_form(mark, new=True)

    def edit_form(self):
        mark_str = self.get_query_arg("mark")
        mark = self.base.lookup(mark_str)
        if not mark:
            raise App400Error("not found: " + mark_str)

        return self._edit_form(mark, new=False)

    def _edit_form(self, mark, new):
        same_url_marks = self.base.find_by_url(mark.url) if new else []
        stopwords = [w for lang in self.user['stopwords'] for w in nltk_stopwords.words(lang)]
        similar = self.base.find_similar(mark, stopwords=stopwords)

        jsondict = self.create_jsondict()
        jsondict.update({
                "mark": mark,
                "current_tag":      f"[{WHITESTAR}]"        if new else WHITESTAR,
                "href_current_tag": None                    if new else url_mark(mark, self.userpath),
                "s_action_edit":    self.userpath + '/edit' if new else url_mark(mark, self.userpath),
                "s_action_delete":  None                    if new else self.userpath + '/delete',
                "same_url_marks": same_url_marks,
                "similar_marks": similar,
            })
        self.respond("200 OK", [('Content-type', 'text/html; charset=utf-8')])
        return [slasti.template.render("html_editform.html", jsondict)]

    # The name edit_post() is a bit misleading, because POST to /edit is used
    # to create new marks, not to edit existing ones (see mark_post() for that).
    def edit_post(self):
        argd = self.find_post_args()

        mark_str = self.base.add1(argd['title'], argd['href'], argd['extra'],
                                  tagbase.split_tags(argd['tags']))
        if not mark_str:
            raise App404Error("Could not add bookmark!")

        redihref = '%s/mark.%s' % (self.userpath, mark_str)

        response_headers = [('Content-type', 'text/html; charset=utf-8')]
        response_headers.append(('Location', redihref))
        self.respond("303 See Other", response_headers)

        jsondict = self.create_jsondict()
        jsondict["us_redirect"] = redihref
        return [slasti.template.render("html_redirect.html", jsondict)]

    def delete_post(self):
        self.base.delete(self.base.lookup(self.get_pinput_arg("mark")))

        self.respond("200 OK", [('Content-type', 'text/html; charset=utf-8')])
        jsondict = self.create_jsondict()
        return [slasti.template.render("html_delete.html", jsondict)]

    def page_any_html(self, mark_top, mark_list, what,
                      jsondict_extra, linkmaker):

        if self.get_query_arg('nopage') == '1':
            pagesize = sys.maxsize
        else:
            pagesize = PAGESZ

        mark_list = list(mark_list)
        if mark_top:
            index = mark_list.index(mark_top)
            if index <= 0:
                mark_prev = None
            else:
                mark_prev = mark_list[max(0, index - pagesize)]
        else:
            index = 0
            mark_prev = None
        mark_next = list_get_default(mark_list, index + pagesize, default=None)

        output_marks = mark_list[index : index + pagesize]

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

        query = self.get_query_arg('q').strip()
        if not query:
            # If q is missing/empty (e.g. search for ""), redirect to homepage
            response_headers = [('Content-type', 'text/html; charset=utf-8'),
                                ('Location', self.userpath)]
            self.respond("303 See Other", response_headers)

            jsondict = self.create_jsondict()
            jsondict["us_redirect"] = self.userpath
            return [slasti.template.render("html_redirect.html", jsondict)]

        marks = self.base.get_marks()
        try:
            search = SearchStrParser(query)
        except SearchStrParser.ParsingError as e:
            return self.page_any_html(
                None, [],
                what="[ search error ]",
                jsondict_extra={ "val_search": query,
                                 "search_error": e.explanation },
                linkmaker=lambda mark: url_search(None, query, self.userpath))

        def contains(needle, mark):
            if needle.startswith('tag:'):
                return needle[4:] in mark.tags
            else:
                return mark.contains(needle)
        marks = [m for m in marks if search.evaluate(
                              callback=lambda needle: contains(needle, m))]

        mark_str = self.get_query_arg('firstmark')
        if mark_str:
            mark = self.base.lookup(mark_str)
            if not mark:
                raise App404Error("Bookmark not found: " + mark_str)
            if mark not in marks:
                raise App404Error("Bookmark not in results list: " + mark_str)
        else:
            mark = None  # Start at first mark

        return self.page_any_html(
                mark, marks,
                what="[ search results ]",
                jsondict_extra={ "val_search": query },
                linkmaker=lambda mark: url_search(mark, query, self.userpath))

    def mark_post(self, mark):
        argd = self.find_post_args()

        tags = tagbase.split_tags(argd['tags'])
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

