#
# Slasti -- Mark/Tag database
#
# Copyright (C) 2011 Pete Zaitcev
# See file COPYING for licensing information (expect GPL 2).
#



import os
import time
import cgi
import difflib
import sqlite3
import urllib.parse

from slasti import AppError
import slasti


def split_marks(tagstr):
    return [t for t in tagstr.split(' ') if t]

class DBMark:
    def __init__(self, from_dict=None, title=None, url=None, tags=None, note=None):
        if from_dict is None:
            self.title = title
            self.url = url
            self.tags = tags
            self.note = note
            return

        self.id = from_dict["mark_id"]
        self.title = from_dict["title"]
        self.url = from_dict["url"]
        self.note = from_dict["note"]
        self.tags = from_dict["tags"]
        self.time = from_dict["time"]

    def __eq__(self, rhs):
        try:
            return self.id == rhs.id
        except Exception:
            return False

    def __neq__(self, rhs):
        return not self == rhs

    def key_str(self):
        return str(self.id)

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

class DBTag:
    def __init__(self, name, count):
        self.name = name
        self.num_marks = count

    def __str__(self):
        return self.name

class SlastiDB:
    def __init__(self, dirname):
        self.dirname = dirname.rstrip('/')
        self.dbfname = self.dirname + '/' + 'bookmarks.db'
        must_create_schema = not os.path.isfile(self.dbfname)

        self.dbconn = sqlite3.connect(self.dbfname)
        self.dbconn.row_factory = sqlite3.Row
        self.dbconn.execute("PRAGMA foreign_keys = ON;")
        if must_create_schema:
            self._create_schema()

    def _create_schema(self):
        self.dbconn.executescript("""
            CREATE TABLE marks(
                mark_id INTEGER PRIMARY KEY,
                time INTEGER NOT NULL,
                title TEXT COLLATE NOCASE,
                url TEXT NOT NULL,
                note TEXT
            );
            CREATE TABLE tags(
                tag_id INTEGER PRIMARY KEY,
                tag TEXT UNIQUE NOT NULL COLLATE NOCASE
            );
            CREATE TABLE mark_tags(
                mark_id INTEGER NOT NULL,
                tag_id INTEGER NOT NULL,
                PRIMARY KEY (mark_id, tag_id),
                FOREIGN KEY (mark_id) REFERENCES marks(mark_id)
                    ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES tags(tag_id) ON DELETE CASCADE
            );
        """)

    def add1(self, title, url, note, tags):
        return self.insert(DBMark(from_dict={"mark_id": None,
                                             "title": title,
                                             "url": url,
                                             "note": note,
                                             "tags": tags,
                                             "time": int(time.time())
                        }))

    def edit1(self, mark, title, url, note, new_tags):
        mark.title = title
        mark.url = url
        mark.note = note
        mark.tags = new_tags
        self.update(mark)

    def insert(self, mark):
        cur = self.dbconn.cursor()
        cur.execute("""INSERT INTO marks(time, title, url, note)
                              VALUES (?, ?, ?, ?);""",
                    (mark.time, mark.title, mark.url, mark.note))
        m_id = cur.execute("SELECT last_insert_rowid()").fetchone()[0]
        for tag in mark.tags:
            tag = tag.strip()
            if not tag:
                continue
            cur.execute("INSERT OR IGNORE INTO tags(tag) VALUES (?);", (tag,))
            cur.execute("SELECT tag_id FROM tags WHERE tag = ?;", (tag,))
            t_id = cur.fetchone()[0]
            cur.execute("INSERT INTO mark_tags VALUES (?, ?);", (m_id, t_id))
        self.dbconn.commit()
        return m_id

    def update(self, mark):
        cur = self.dbconn.cursor()
        cur.execute("""UPDATE marks SET time = ?, title = ?, url = ?, note = ?
                              WHERE mark_id = ?;""",
                    (mark.time, mark.title, mark.url, mark.note, mark.id))

        cur.execute("""DELETE FROM mark_tags WHERE mark_id = ?;""", (mark.id,))
        for tag in mark.tags:
            tag = tag.strip()
            if not tag:
                continue
            cur.execute("INSERT OR IGNORE INTO tags(tag) VALUES (?);", (tag,))
            cur.execute("SELECT tag_id FROM tags WHERE tag = ?;", (tag,))
            t_id = cur.fetchone()[0]
            cur.execute("INSERT INTO mark_tags VALUES (?,?);", (mark.id, t_id))
        cur.execute("""DELETE FROM tags WHERE tag_id NOT IN
                              (SELECT mark_tags.tag_id FROM mark_tags);""")
        self.dbconn.commit()
        return mark.id

    def delete(self, mark):
        cur = self.dbconn.cursor()
        cur.execute("""DELETE FROM marks WHERE mark_id = ?;""", (mark.id,))
        cur.execute("""DELETE FROM tags WHERE tag_id NOT IN
                              (SELECT mark_tags.tag_id FROM mark_tags);""")
        self.dbconn.commit()

    def _mark_from_dbrow(self, row):
        d = dict(row)
        d["tags"] = d["tags"].split()
        return DBMark(from_dict=d)

    def _get_marks(self, *, mark_id=None, tag=None, url=None):
        where_mark = '''WHERE mark_id = :mark_id''' if mark_id else ''
        where_tag =  '''WHERE mark_id in (SELECT mark_id FROM mark_tags
                                          JOIN tags USING (tag_id)
                                          WHERE tag = :tag)''' if tag else ''
        where_url = '''WHERE url = :url''' if url is not None else ''
        stmt = """SELECT marks.*, group_concat(tag, ' ') AS tags FROM marks
                  JOIN mark_tags USING (mark_id)
                  JOIN tags USING (tag_id)
                  {where_mark} {where_tag} {where_url}
                  GROUP BY mark_id
                  ORDER BY time DESC;""".format(where_mark=where_mark,
                                                where_tag=where_tag,
                                                where_url=where_url)

        rows = self.dbconn.execute(stmt, { 'mark_id': mark_id, 'tag': tag, 'url': url })
        return (self._mark_from_dbrow(row) for row in rows)

    def lookup(self, mark_id):
        result = list(self._get_marks(mark_id=int(mark_id)))
        if not result:
            return None
        return result[0]

    def get_headers(self, tag=None):
        for mark in self.get_marks():
            yield mark

    def get_marks(self):
        return self._get_marks()

    def get_tag_marks(self, tag):
        return self._get_marks(tag=tag)

    def get_tags(self):
        rows = self.dbconn.execute(
                """SELECT tag, count(mark_id) AS cnt FROM tags
                          JOIN mark_tags USING (tag_id)
                          GROUP BY tag_id
                          ORDER BY tag ASC;""")
        for row in rows:
            yield DBTag(row[0], row[1])

    def find_by_url(self, url):
        return list(self._get_marks(url=url))
