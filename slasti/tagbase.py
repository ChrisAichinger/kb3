#
# Slasti -- Mark/Tag database
#
# Copyright (C) 2011 Pete Zaitcev
# See file COPYING for licensing information (expect GPL 2).
#

import sys
import os
import functools
import multiprocessing as mp
import pickle
import re
import sqlite3
import time

from nltk.corpus import stopwords as nltk_stopwords
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

from slasti import AppError
import slasti


def split_tags(tagstr):
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


@functools.lru_cache(maxsize=None)
def stopwords_from_language(lang):
    return nltk_stopwords.words(lang)


class SlastiDB:
    def __init__(self, dbfname, stopwords=None, stopword_languages=None, ignore_hosts_in_search=()):
        self.dbfname = dbfname
        must_create_schema = not os.path.isfile(self.dbfname)

        self.dbconn = sqlite3.connect(self.dbfname)
        self.dbconn.row_factory = sqlite3.Row
        self.dbconn.execute("PRAGMA foreign_keys = ON;")

        self.cache = DBCache(self.dbconn)
        if must_create_schema:
            self._create_schema()
            self.cache.create_schema()

        self.stopwords = stopwords
        if stopword_languages:
            self.stopwords = list(self.stopwords or [])
            self.stopwords.extend(
                w for lang in stopword_languages
                    for w in stopwords_from_language(lang))
        self.ignore_hosts_in_search = ignore_hosts_in_search

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
        result = self.insert(DBMark(from_dict={"mark_id": None,
                                               "title": title,
                                               "url": url,
                                               "note": note,
                                               "tags": tags,
                                               "time": int(time.time())
                        }))
        self.async_update_similarity_cache()
        return result

    def edit1(self, mark, title, url, note, new_tags):
        mark.title = title
        mark.url = url
        mark.note = note
        mark.tags = new_tags
        self.update(mark)
        self.async_update_similarity_cache()

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
        self.cache.invalidate_cursor(cur)
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
        self.cache.invalidate_cursor(cur)
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

    def find_similar(self, mark, *, num=10):
        cached_search = self.cache.get('similarity')
        if cached_search:
            search = SimilaritySearch.deserialize(cached_search)
        else:
            print("Warning: Out-of-date similarity cache found", file=sys.stderr, flush=True)
            search = self._refresh_similarity_cache()
        similar_ids = search.find_similar_ids(mark, num=num)
        return [m
                for id in similar_ids
                    for m in self._get_marks(mark_id=id)]

    def async_update_similarity_cache(self):
        def f(dbfname, stopwords, ignore_hosts_in_search):
            db = SlastiDB(dbfname, stopwords=stopwords, ignore_hosts_in_search=ignore_hosts_in_search)
            db._refresh_similarity_cache()
        p = mp.Process(target=f, args=(self.dbfname, self.stopwords, self.ignore_hosts_in_search))
        p.start()

    def _refresh_similarity_cache(self):
        search = SimilaritySearch(self.stopwords, self.ignore_hosts_in_search)
        search.load_corpus(list(self._get_marks()))
        self.cache.set('similarity', search.serialize())
        return search


class DBCache:
    def __init__(self, dbconn):
        self.dbconn = dbconn

    def create_schema(self):
        self.dbconn.executescript("""
            CREATE TABLE cache(
                key TEXT UNIQUE NOT NULL,                 -- cache key
                value BLOB,                               -- cached value
                change_id INTEGER NOT NULL DEFAULT 0,     -- incremented on any DB write
                refresh_id INTEGER NOT NULL DEFAULT -1,   -- equals change_id if up to date

                PRIMARY KEY (key)
            );
        """)

    def invalidate_cursor(self, cur):
        cur.execute("UPDATE cache SET change_id = change_id + 1")

    def invalidate(self):
        cur = self.dbconn.cursor()
        self.invalidate_cursor(cur)
        self.dbconn.commit()

    def set(self, key, value):
        row = self.dbconn.execute("SELECT change_id FROM cache where key = ?", (key,)).fetchone()
        current_change_id = row['change_id'] if row else None

        cur = self.dbconn.cursor()
        cur.execute("""
             INSERT INTO cache(key, value) VALUES (?, ?)
             ON CONFLICT (key) DO
             UPDATE SET value = excluded.value, refresh_id = ?
             """, (key, value, current_change_id))
        self.dbconn.commit()

    def get(self, key):
        row = self.dbconn.execute(
            """SELECT value
                 FROM cache
                WHERE key = ?
                  AND change_id = refresh_id""",
            (key,)).fetchone()
        return row['value'] if row else None


class SimilaritySearch:
    def __init__(self, stopwords, ignore_hosts):
        self.stopwords = stopwords
        self.ignore_hosts = ignore_hosts
        self.vectorizers = dict()  # Vectorizer for each column
        self.db_vectors = dict()   # Sparse Matrix of documents/terms
        self.db_ids = []           # Map from matrix indices to Mark IDs

    def serialize(self):
        return pickle.dumps(self)

    @classmethod
    def deserialize(cls, s):
        return pickle.loads(s)

    def load_corpus(self, all_marks):
        marks_data = [self._mark_to_dict(m) for m in all_marks]
        self._load_column_corpus(marks_data, 'tags')
        self._load_column_corpus(marks_data, 'title', stop_words=self.stopwords)
        self._load_column_corpus(marks_data, 'note', stop_words=self.stopwords)
        self._load_column_corpus(marks_data, 'host', token_pattern='.*')
        self.db_ids = [m['id'] for m in marks_data]

    def find_similar_ids(self, mark, *, num=10):
        mark_id = getattr(mark, 'id', None)
        mark_data = self._mark_to_dict(mark)
        sim = (
            0.15 * self._similarity(mark_data, 'tags') +
            0.50 * self._similarity(mark_data, 'title') +
            0.25 * self._similarity(mark_data, 'note') +
            0.10 * self._similarity(mark_data, 'host')
        )
        best_doc_indices = sim.argsort()
        best_mark_ids = [self.db_ids[i] for i in best_doc_indices[:-num-1:-1]]
        return [bm_id for bm_id in best_mark_ids if bm_id != mark_id][:num]

    def _load_column_corpus(self, marks, column, **kwargs):
        db_texts = [m[column] for m in marks]
        self.vectorizers[column] = TfidfVectorizer(**kwargs)
        self.db_vectors[column] = self.vectorizers[column].fit_transform(db_texts)

    def _similarity(self, mark, column, **kwargs):
        vectorizer = self.vectorizers[column]
        db_vec = self.db_vectors[column]
        mark_text = mark[column] or ''
        mark_vec = vectorizer.transform([mark_text])
        return linear_kernel(db_vec, mark_vec).flatten()

    def _mark_to_dict(self, mark):
        m = mark.__dict__.copy()
        m['tags'] = ' '.join(m['tags'] or '')
        h = re.match(r'[^/]*///*([^/]*)', m['url'] or '')
        m['host'] = h.group(1) if h else ''
        for ih in self.ignore_hosts:
            if ih in m['host']:
                m['host'] = ''
        return m
