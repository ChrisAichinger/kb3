#
# Slasti -- Mark/Tag database
#
# Copyright (C) 2011 Pete Zaitcev
# See file COPYING for licensing information (expect GPL 2).
#

import sys
import os
from dataclasses import dataclass
import functools
import multiprocessing as mp
import pickle
import re
import sqlite3
import subprocess
import time
from urllib.parse import urlparse


from bs4 import BeautifulSoup
from nltk.corpus import stopwords as nltk_stopwords
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

Sentinel = object()


@functools.lru_cache(maxsize=None)
def stopwords_from_language(lang):
    return nltk_stopwords.words(lang)


def extract_links(markdown):
    p = subprocess.run(
        ['pandoc', '-f', 'commonmark', '-t', 'html'],
        input=markdown, capture_output=True,
        encoding='utf-8', check=True)
    soup = BeautifulSoup(p.stdout, features="lxml")
    for tag in soup.find_all('a'):
        href = tag.get('href')
        if href is not None:
            yield ''.join(str(c) for c in tag.contents), href


class Bookmark:
    def __init__(self, *, id=None, title=None, url=None, tags=None, note=None, time=None, incoming_links=None):
        incoming_links = incoming_links or []
        self.update(id=id, title=title, url=url, tags=tags, note=note, time=time, incoming_links=incoming_links)

    def update(self, *, id=Sentinel, title=Sentinel, url=Sentinel, tags=Sentinel, note=Sentinel,
               time=Sentinel, incoming_links=Sentinel):
        if id is not Sentinel:
            self.id = id
        if title is not Sentinel:
            self.title = title
        if url is not Sentinel:
            self.url = url
        if tags is not Sentinel:
            self.tags = tags
        if note is not Sentinel:
            self.note = note
        if time is not Sentinel:
            self.time = time
        if incoming_links is not Sentinel:
            self.incoming_links = incoming_links

    @property
    def tags(self):
        return self._tags

    @tags.setter
    def tags(self, tags):
        if isinstance(tags, str):
            tags = [t for t in tags.split(' ') if t]
        self._tags = tags

    @property
    def stars(self):
        matching_tags = [re.match(r'^([0-5])star$', tag) for tag in self.tags]
        star_list = [int(m.group(1)) for m in matching_tags if m]
        return max(star_list, default=0)

    def __eq__(self, rhs):
        if self.id is not None:
            return self.id == rhs.id
        return (self.title == rhs.title and
                self.url == rhs.url and
                self.tags == rhs.tags and
                self.note == rhs.note and
                self.time == rhs.time)

    def __neq__(self, rhs):
        return not self == rhs

    def __repr__(self):
        return f"<{self.__class__.__name__} id={self.id} title={self.title[:30]}>"

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


@dataclass
class SlimBookmark:
    '''Rudimentary bookmark information: id, title, url'''
    id: int
    title: str
    url: str
    time: int


@dataclass
class Tag:
    '''Meta-information about a tag: tab name and bookmark count'''
    name: str
    num_marks: int

    def __str__(self):
        return self.name


class SlastiDB:
    def __init__(self, dbfname, abs_url_prefix, stopwords=None, stopword_languages=None, ignore_hosts_in_search=()):
        self.dbfname = dbfname
        must_create_schema = not os.path.isfile(self.dbfname)

        self.dbconn = sqlite3.connect(self.dbfname)
        self.dbconn.row_factory = sqlite3.Row
        self.dbconn.execute("PRAGMA foreign_keys = ON;")

        self.cache = DBCache(self.dbconn)
        if must_create_schema:
            self._create_schema()
            self.cache.create_schema()

        self.abs_url_prefix = abs_url_prefix
        rel_url_prefix = urlparse(abs_url_prefix).path
        escaped_prefixes = (re.escape(p) for p in [abs_url_prefix, rel_url_prefix])
        self.crosslink_regex = re.compile(r'^({})/mark\.(\d+)$'.format('|'.join(escaped_prefixes)))

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
                FOREIGN KEY (mark_id) REFERENCES marks(mark_id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES tags(tag_id) ON DELETE CASCADE
            );
        """)

    def add(self, title, url, note, tags):
        mark_id = self._insert(Bookmark(title=title, url=url, note=note, tags=tags, time=int(time.time())))
        self.async_update_similarity_cache()
        return mark_id

    def edit(self, mark, *, title=Sentinel, url=Sentinel, note=Sentinel, tags=Sentinel):
        mark.update(title=title, url=url, note=note, tags=tags)
        self._update(mark)
        self.async_update_similarity_cache()

    def _insert(self, mark):
        cur = self.dbconn.cursor()
        cur.execute("""INSERT INTO marks(time, title, url, note)
                              VALUES (?, ?, ?, ?);""",
                    (mark.time, mark.title, mark.url, mark.note))
        mark.id = m_id = cur.execute("SELECT last_insert_rowid()").fetchone()[0]
        for tag in mark.tags:
            tag = tag.strip()
            if not tag:
                continue
            cur.execute("INSERT OR IGNORE INTO tags(tag) VALUES (?);", (tag,))
            t_id = cur.execute("SELECT tag_id FROM tags WHERE tag = ?;", (tag,)).fetchone()[0]
            cur.execute("INSERT INTO mark_tags VALUES (?, ?);", (m_id, t_id))
        self._save_crosslinks(mark, cur)
        self.cache.invalidate_cursor(cur)
        self.dbconn.commit()
        return m_id

    def _update(self, mark):
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
        self._save_crosslinks(mark, cur)
        self.cache.invalidate_cursor(cur)
        self.dbconn.commit()
        return mark.id

    def _save_crosslinks(self, mark, cur):
        cur.execute("DELETE FROM mark_crosslinks WHERE source_id = ?", (mark.id,))
        for link_title, url in extract_links(mark.note):
            m = self.crosslink_regex.match(url)
            if m:
                cur.execute("INSERT OR REPLACE INTO mark_crosslinks VALUES (?, ?, ?);",
                            (mark.id, m.group(2), link_title))

    def delete(self, mark):
        cur = self.dbconn.cursor()
        cur.execute("""DELETE FROM marks WHERE mark_id = ?;""", (mark.id,))
        cur.execute("""DELETE FROM mark_crosslinks WHERE source_id = ?""", (mark.id,))
        cur.execute("""DELETE FROM tags WHERE tag_id NOT IN
                              (SELECT mark_tags.tag_id FROM mark_tags);""")
        self.dbconn.commit()

    def get_successors(self, mark_id=None, count=1):
        stmt = """SELECT * FROM (
                      SELECT marks.*, group_concat(tag, ' ') AS tags FROM marks
                      JOIN mark_tags USING (mark_id)
                      JOIN tags USING (tag_id)
                      WHERE mark_id > :mark_id
                      GROUP BY mark_id
                      ORDER BY mark_id ASC
                      LIMIT :count
                  ) ORDER BY mark_id DESC
               """
        rows = self.dbconn.execute(stmt, { 'mark_id': mark_id, 'count': count })
        return [self._mark_from_dbrow(row) for row in rows]

    def get_predecessors(self, mark_id=None, count=1):
        stmt = """SELECT marks.*, group_concat(tag, ' ') AS tags FROM marks
                  JOIN mark_tags USING (mark_id)
                  JOIN tags USING (tag_id)
                  WHERE mark_id < :mark_id
                  GROUP BY mark_id
                  ORDER BY mark_id DESC
                  LIMIT :count"""
        rows = self.dbconn.execute(stmt, { 'mark_id': mark_id, 'count': count })
        return [self._mark_from_dbrow(row) for row in rows]

    def _mark_from_dbrow(self, row):
        return Bookmark(id=row["mark_id"], title=row["title"], url=row["url"],
                        note=row["note"], tags=row["tags"].split(), time=row["time"])

    def get_marks(self, *, limit=-1, offset=0, mark_id=None, not_mark_id=None, tag=None, url=None):
        where_clauses = ["1=1"]
        if mark_id is not None:
            where_clauses.append('mark_id = :mark_id')
        if not_mark_id is not None:
            where_clauses.append('mark_id != :not_mark_id')
        if tag is not None:
            where_clauses.append('''mark_id in (SELECT mark_id FROM mark_tags
                                                JOIN tags USING (tag_id)
                                                WHERE tag = :tag)''')
        if url is not None:
            where_clauses.append('url = :url')
        stmt = f"""SELECT marks.*, group_concat(tag, ' ') AS tags
                     FROM marks
                     JOIN mark_tags USING (mark_id)
                     JOIN tags USING (tag_id)
                    WHERE {' AND '.join(where_clauses)}
                 GROUP BY mark_id
                 ORDER BY mark_id DESC
                    LIMIT :limit
                   OFFSET :offset;"""
        args = dict(
            mark_id=mark_id,
            not_mark_id=not_mark_id,
            tag=tag,
            url=url,
            limit=limit,
            offset=offset,
        )
        rows = self.dbconn.execute(stmt, args)
        bookmarks = [self._mark_from_dbrow(row) for row in rows]
        self._add_incoming_links(bookmarks)
        return bookmarks

    def _add_incoming_links(self, bookmarks):
        id_bookmark_map = {m.id: m for m in bookmarks}
        for m in bookmarks:
            m.incoming_links = []

        stmt = f"""SELECT mark_crosslinks.destination_id, mark_id, title, url, time
                     FROM mark_crosslinks
                     JOIN marks ON mark_crosslinks.source_id = marks.mark_id
                    WHERE mark_crosslinks.destination_id in ({','.join(['?']*len(id_bookmark_map))})
                 ORDER BY marks.mark_id DESC;"""
        rows = self.dbconn.execute(stmt, list(id_bookmark_map))
        for dst_id, src_id, src_title, src_url, src_time in rows:
            link = SlimBookmark(src_id, src_title, src_url, src_time)
            id_bookmark_map[dst_id].incoming_links.append(link)

    def lookup(self, mark_id):
        result = self.get_marks(mark_id=int(mark_id))
        if not result:
            return None
        return result[0]

    def get_tags(self, sort_by_frequency=False):
        if sort_by_frequency:
            sorter = "count(mark_id) DESC"
        else:
            sorter = "tag ASC"
        rows = self.dbconn.execute(
                """SELECT tag, count(mark_id) AS cnt FROM tags
                          JOIN mark_tags USING (tag_id)
                          GROUP BY tag_id
                          ORDER BY """ + sorter + ";")
        for row in rows:
            yield Tag(row[0], row[1])

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
                    for m in self.get_marks(mark_id=id)]

    def async_update_similarity_cache(self):
        def f(self):
            db = SlastiDB(self.dbfname, self.abs_url_prefix, stopwords=self.stopwords,
                          ignore_hosts_in_search=self.ignore_hosts_in_search)
            db._refresh_similarity_cache()
        p = mp.Process(target=f, args=(self,))
        p.start()

    def _refresh_similarity_cache(self):
        search = SimilaritySearch(self.stopwords, self.ignore_hosts_in_search)
        search.load_corpus(self.get_marks())
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
        m['tags'] = ' '.join(m['_tags'] or '')
        del m['_tags']
        h = re.match(r'[^/]*///*([^/]*)', m['url'] or '')
        m['host'] = h.group(1) if h else ''
        for ih in self.ignore_hosts:
            if ih in m['host']:
                m['host'] = ''
        return m
