#
# Slasti -- Mark/Tag database
#
# Copyright (C) 2011 Pete Zaitcev
# See file COPYING for licensing information (expect GPL 2).
#
# requires:
#  codecs
#
from __future__ import unicode_literals
from __future__ import print_function

ENC = "utf-8"
import codecs
utf8_writer = codecs.getwriter(ENC)
import os
import errno
import time
# import urllib
import cgi
import base64
import urllib

from slasti import AppError
import slasti

# A WSGI module running on Fedora 15 gets no LANG, so Python decides
# that filesystem encoding is "ascii". This cannot be changed.
# Then, an attempt to call open(basedir + "/" + tag) blows up with
# "UnicodeDecodeError: 'ascii' codec can't decode byte 0xe3 in posi...".
# Manual encoding does not work, it still blows up even if argument is str.
# The only way is to avoid UTF-8 filenames entirely.

def fs_encode(tag):
    return base64.b64encode(slasti.safestr(tag), b"+_")

def fs_decode(tag):
    # XXX try TypeError -- and then what?
    s = base64.b64decode(tag, b"+_")
    # XXX try UnicodeDecodeError -- and then what?
    u = s.decode(ENC)
    return u

def fs_decode_list(names):
    ret = []
    for s in names:
        # Encoding with ascii? Why, yes. In F15, listdir returns unicode
        # strings, but b64decode blows up on them (deep in .translate()
        # not having the right table). Force back into str. They are base64
        # encoded, so 'ascii' is appropriate.
        if isinstance(s, unicode):
            s = s.encode('ascii')
        ret.append(fs_decode(s))
    return ret

def make_keystring(timeint, fix):
    return "%010d.%02d" % (timeint, fix)

def split_marks(tagstr):
    tags = []
    for t in tagstr.split(' '):
        if t:
            tags.append(t)
    return tags

def load_tag(tagdir, tag):
    try:
        f = codecs.open(tagdir + "/" + fs_encode(tag), "r",
                        encoding=ENC, errors="replace")
    except IOError, e:
        f = None
    if f != None:
        # This can be a long read - tens of thousands of mark keys
        tagbuf = f.read()
        f.close()
    else:
        tagbuf = ''
    return tagbuf

def read_tags(markdir, markname):
    try:
        f = codecs.open(markdir + "/" + markname, "r",
                        encoding=ENC, errors="replace")
    except IOError:
        return []

    # self-id: stamp1.stamp2
    s = f.readline()
    if not s:
        f.close()
        return []

    # title (???)
    s = f.readline()
    if not s:
        f.close()
        return []

    # url
    s = f.readline()
    if not s:
        f.close()
        return []

    # note
    s = f.readline()
    if not s:
        f.close()
        return []

    s = f.readline()
    if not s:
        f.close()
        return []
    tags = split_marks(s.rstrip("\r\n"))

    f.close()
    return tags

# def difftags is not just what diff does, but a diff of two sorted lists.

# We just throw it all into a colored list and let the result fall out.
# The cleanest approach would be to merge reds and blues with the same key,
# but we do not know a nice way to do it. So we join and then recolor.

def difftags(old, new):

    # No amount of tinkering with strxfrm, strcoll, and locale settings helps.
    # The sort still blows up with UnicodeDecodeError, codec 'ascii'.
    # So, just safestr the sort keys.

    joint = []
    for s in old:
        joint.append([slasti.safestr(s), s, '-'])
    for s in new:
        joint.append([slasti.safestr(s), s, ' +'])

    joint.sort(None, lambda t: t[0])

    prev = None
    for s in joint:
        if prev != None and prev[0] == s[0]:
            prev[2] = ' ';
            s[2] = ' ';
        prev = s

    minus = []
    plus = []
    for s in joint:
        if s[2] == '-':
            minus.append(s[1])
        if s[2] == '+':
            plus.append(s[1])

    return (minus, plus)

class MarkHeader:
    def __init__(self, base, markname):
        self.base = base
        self.name = markname

    def key_str(self):
        return self.name

    def get(self):
        return TagMark(self.base, self.name)

    def __eq__(self, rhs):
        try:
            return self.key_str() == rhs.key_str()
        except Exception:
            return False

    def __neq__(self, rhs):
        return not self == rhs


#
# TagMark is one bookmark when we manipulate it (extracted from TagBase).
#
class TagMark:
    def __init__(self, base, markname):
        self.base = base
        self.name = markname

        self.stamp0 = 0
        self.stamp1 = 0
        self.title = "-"
        self.url = "-"
        self.note = ""
        self.tags = []

        try:
            f = codecs.open(base.markdir + "/" + self.name, "r",
                            encoding=ENC, errors="replace")
        except IOError:
            # Set a red tag to tell us where we crashed.
            self.stamp1 = 1
            return

        s = f.readline()
        if not s:
            self.stamp1 = 2
            f.close()
            return
        # Format is defined as two integers over a dot, which unfortunately
        # looks like a decimal fraction. Should've used a space. Oh well.
        slist = s.rstrip("\r\n").split(".")
        if len(slist) != 2:
            self.stamp1 = 3
            f.close()
            return

        try:
            self.stamp0 = int(slist[0])
            self.stamp1 = int(slist[1])
        except ValueError:
            self.stamp1 = 4
            f.close()
            return

        s = f.readline()
        if not s:
            f.close()
            return
        self.title = s.rstrip("\r\n")

        s = f.readline()
        if not s:
            f.close()
            return
        self.url = s.rstrip("\r\n")

        s = f.readline()
        if not s:
            f.close()
            return
        self.note = s.rstrip("\r\n")

        s = f.readline()
        if not s:
            f.close()
            return

        s = s.rstrip("\r\n")
        # Stripping spaces prevents emply tags coming out of split().
        s = s.strip(" ")
        self.tags = s.split(" ")

        f.close()

    def __str__(self):
        # There do not seem to be any exceptions raised with weird inputs.
        datestr = time.strftime("%Y-%m-%d", time.gmtime(self.stamp0))
        return '|'.join([self.name, datestr,
                         slasti.safestr(self.title), self.url,
                         slasti.safestr(self.note), slasti.safestr(self.tags)])

    def __eq__(self, rhs):
        try:
            return self.key_str() == rhs.key_str()
        except Exception:
            return False

    def __neq__(self, rhs):
        return not self == rhs

    def get(self):
        return self

    def key_str(self):
        return make_keystring(self.stamp0, self.stamp1)

    def key(self):
        return (self.stamp0, self.stamp1)

    def get_editpath(self, path_prefix):
        return '%s/edit?mark=%s' % (path_prefix, self.key_str())

    def to_jsondict(self, path_prefix):
        title = self.title
        if not title:
            title = self.url

        mark_url = '%s/mark.%s' % (path_prefix, self.key_str())
        ts = time.gmtime(self.stamp0)
        jsondict = {
            "date": unicode(time.strftime("%Y-%m-%d", ts)),
            "xmldate": unicode(time.strftime("%Y-%m-%dT%H:%M:%SZ", ts)),
            "href_mark": mark_url,
            "href_mark_url": slasti.escapeURL(self.url),
            "xmlhref_mark_url": cgi.escape(self.url, True),
            "title": title,
            "note": self.note,
            "tags": [],
            "key": self.key_str(),
        }

        tags_str = []
        for tag in self.tags:
            tags_str.append(tag)
            jsondict["tags"].append(
                {"href_tag": '%s/%s/' % (path_prefix,
                                         slasti.escapeURLComponent(tag)),
                 "name_tag": tag,
                })
        jsondict["tags_str"] = ' '.join(tags_str)

        return jsondict

    def contains(self, string):
        """Search text string in mark - return True if found, else False

        Returns True if string is found within the bookmark (either within
        title, url, notes, or within one of the tags).
        If string is not found, False is returned.
        """
        string = string.lower()
        return (string in self.title.lower() or
                string in self.url.lower() or
                string in self.note.lower() or
                any(tag for tag in self.tags if string in tag.lower())
               )


class TagTag:
    def __init__(self, base, taglist, tagindex):
        self.base = base
        self.name = taglist[tagindex]

        self.nmark = len(split_marks(load_tag(base.tagdir, taglist[tagindex])))

    def __str__(self):
        return self.name

    def key(self):
        return self.name

    def num(self):
        return self.nmark

#
# The open database (any back-end in theory, hardcoded to files for now)
# XXX files are very inefficient: 870 bookmarks from a 280 KB XML take 6 MB.
#
class TagBase:
    def __init__(self, dirname0):
        # An excessively clever way to do the same thing exists, see:
        # http://zaitcev.livejournal.com/206050.html?thread=418530#t418530
        # self.dirname = dirname0[:1] + dirname0[1:].rstrip('/')
        d = dirname0
        if len(d) > 1 and d[-1] == '/':
            d = dirname0[:-1]
        self.dirname = d

        if not os.path.exists(self.dirname):
            raise AppError("Does not exist: " + self.dirname)
        if not os.path.isdir(self.dirname):
            raise AppError("Not a directory: " + self.dirname)

        self.tagdir = self.dirname + "/tags"
        self.markdir = self.dirname + "/marks"

    def open(self):
        try:
            os.mkdir(self.tagdir)
        except OSError, e:
            if e.errno != errno.EEXIST:
                raise AppError(str(e))
        try:
            os.mkdir(self.markdir)
        except OSError, e:
            if e.errno != errno.EEXIST:
                raise AppError(str(e))

    def close(self):
        pass

    #
    # XXX Add locking for consistency of concurrent updates

    # Store the mark body
    def store(self, markname, stampkey, title, url, note, tags):
        try:
            f = open(self.markdir + "/" + markname, "w+")
        except IOError, e:
            raise AppError(str(e))

        # This is done because ElementTree throws Unicode strings at us.
        # When we try to write these strings, UnicodeEncodeError happens.
        f = utf8_writer(f)

        # We write the key into the file in case we ever decide to batch marks.
        print(stampkey, file=f)
        print(title, file=f)
        print(url, file=f)
        print(note, file=f)
        print(" " + " ".join(tags), file=f)

        f.close()

    # Add tag links for a new mark (still, don't double-add)
    def links_add(self, markname, tags):
        for t in tags:
            # 1. Read
            tagbuf = load_tag(self.tagdir, t)
            # 2. Modify
            # It would be more efficient to scan by hand instead of splitting,
            # but premature optimization is the root etc.
            if markname in split_marks(tagbuf):
                continue
            tagbuf = tagbuf + " " + markname
            # 3. Write
            try:
                f = open(self.tagdir + "/" + fs_encode(t), "w")
            except IOError, e:
                continue
            f.write(tagbuf)
            f.close()

    def links_del(self, markname, tags):
        for t in tags:
            # 1. Read
            tagbuf = load_tag(self.tagdir, t)
            # 2. Modify
            mark_list = split_marks(tagbuf)
            if not markname in mark_list:
                continue
            mark_list.remove(markname)
            # 3. Write
            if len(mark_list) != 0:
                tagbuf = " ".join(mark_list)
                try:
                    f = open(self.tagdir + "/" + fs_encode(t), "w")
                except IOError, e:
                    continue
                f.write(tagbuf)
                f.close()
            else:
                os.remove(self.tagdir + "/" + fs_encode(t))

    def links_edit(self, markname, old_tags, new_tags):
        tags_drop, tags_add = difftags(old_tags, new_tags)
        # f = open("/tmp/slasti.run", "w")
        # print >>f, str(old_tags)
        # print >>f, str(new_tags)
        # print >>f, str(tags_drop)
        # print >>f, str(tags_add)
        # f.close()
        self.links_del(markname, tags_drop)
        self.links_add(markname, tags_add)

    # The add1 constructs key from UNIX seconds.
    def add1(self, title, url, note, tags):
        timeint = int(time.time())
        # for normal website-entered content fix is usually zero
        fix = 0
        while 1:
            stampkey = make_keystring(timeint, fix)
            if not os.path.exists(self.markdir + "/" + stampkey):
                break
            fix += 1
            if fix >= 100:
                return None

        self.store(stampkey, stampkey, title, url, note, tags)
        self.links_add(stampkey, tags)
        return make_keystring(timeint, fix)

    # Edit a presumably existing tag.
    def edit1(self, mark, title, url, note, new_tags):
        timeint, fix = mark.key_str()
        stampkey = make_keystring(timeint, fix)
        old_tags = read_tags(self.markdir, stampkey)
        self.store(stampkey, stampkey, title, url, note, new_tags)
        self.links_edit(stampkey, old_tags, new_tags)

    def delete(self, mark):
        timeint, fix = mark.key()
        stampkey = make_keystring(timeint, fix)
        old_tags = read_tags(self.markdir, stampkey)
        self.links_del(stampkey, old_tags)
        try:
            os.unlink(self.markdir + "/" + stampkey)
        except IOError, e:
            raise AppError(str(e))

    def _full_dlist(self):
        # Would be nice to cache the directory in TagBase somewhere.
        # Should we catch OSError here, incase of lookup on un-opened base?
        return sorted(os.listdir(self.markdir), reverse=True)

    def lookup(self, mark_str):
        p = mark_str.split(".")
        try:
            timeint = int(p[0])
            fix = int(p[1])
        except (ValueError, IndexError):
            return None

        matchname = make_keystring(timeint, fix)
        if matchname not in self._full_dlist():
            return None
        return TagMark(self, matchname)

    def get_headers(self, tag=None):
        dlist = self._full_dlist()
        for idx in range(len(dlist)):
            yield MarkHeader(self, dlist[idx])

    def get_marks(self, tag=None):
        dlist = self._full_dlist()
        for idx in range(len(dlist)):
            yield TagMark(self, dlist[idx])

    def get_tag_marks(self, tag):
        dlist = sorted(split_marks(load_tag(self.tagdir, tag)), reverse=True)
        for idx in range(len(dlist)):
            yield TagMark(self, dlist[idx])

    def get_tags(self):
        dlist = sorted(fs_decode_list(os.listdir(self.tagdir)))
        for index in range(len(dlist)):
            yield TagTag(self, dlist, index)
