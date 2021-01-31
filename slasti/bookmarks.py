import os
import functools
import re
import time
import types

from flask import Blueprint, flash, g, redirect, render_template, request, url_for, current_app
from werkzeug.exceptions import abort

from . import tagbase
from .search import SearchStrParser

BLACKSTAR = "\u2605"
WHITESTAR = "\u2606"


@functools.lru_cache(maxsize=2048)
def url_for_current_user(view, **kwargs):
    return url_for(view, user=g.user.name, **kwargs)

def format_date(mark_time):
    return time.strftime('%Y-%m-%d', time.gmtime(mark_time))


#################
# Blueprint setup
#################

bp = Blueprint('bookmarks', __name__)

@bp.before_request
def initialize_context():
    if request.path == '/':
        return

    m = re.match(r"/([^/]+)", request.path)
    if not m:
        abort(404, "No such path or user")

    user = current_app.config['SLASTI_USERS'].get(m.group(1))
    if not user:
        abort(404, f"No such user")

    g.user = types.SimpleNamespace(**user)
    abs_url_prefix = current_app.config['SLASTI_ABS_URL'].rstrip('/') + '/' + user['name']
    g.db = tagbase.SlastiDB(os.path.join(current_app.config['BASE_DIR'], user['database']),
                            abs_url_prefix,
                            stopwords=user.get('stopwords', []),
                            stopword_languages=user.get('stopword_languages', []),
                            ignore_hosts_in_search=user.get('ignore_hosts_in_search', []))

    current_app.jinja_env.globals['url_for_current_user'] = url_for_current_user
    current_app.jinja_env.globals['WHITESTAR'] = WHITESTAR
    current_app.jinja_env.globals['BLACKSTAR'] = BLACKSTAR
    current_app.jinja_env.filters['format_date'] = format_date


#########################################
# Views for displaying existing bookmarks
#########################################

@bp.route('/')
def index():
    return "Anti-social bookmarking."


@bp.route('/<user>', defaults={'tag_name': None})
@bp.route('/<user>/tags/<tag_name>')
def list_view(user, tag_name):
    offset = request.args.get("offset", type=int, default=0)
    pagesize = request.args.get("pagesize", type=int, default=current_app.config['SLASTI_PAGE_SIZE'])

    if not tag_name and tag_name is not None:
        redirect(url_for_current_user('.list_view'), 303)

    title = tag_name if tag_name else None
    marks = g.db.get_marks(tag=tag_name, offset=offset, limit=pagesize)

    next_link = prev_link = None
    if offset > 0:
        prev_offset = max(offset - pagesize, 0)
        prev_link = url_for_current_user('.list_view', offset=prev_offset, pagesize=pagesize, tag_name=tag_name)
    if len(marks) == pagesize:
        # If total_mark_count % pagesize == 0, we display an empty last page. We'll live with this.
        next_offset = offset + pagesize
        next_link = url_for_current_user('.list_view', offset=next_offset, pagesize=pagesize, tag_name=tag_name)

    return render_template('html_mark.html', title=title, marks=marks, next_page_link=next_link, prev_page_link=prev_link)


@bp.route('/<user>/mark.<int:mark_id>')
def mark_view(user, mark_id):
    mark = g.db.lookup(mark_id)
    if mark is None:
        abort(404, f"Mark not found: {mark_id}")

    succs = g.db.get_successors(mark_id, count=1)
    preds = g.db.get_predecessors(mark_id, count=1)
    succ_link = url_for_current_user(".mark_view", mark_id=succs[0].id) if succs else None
    pred_link = url_for_current_user(".mark_view", mark_id=preds[0].id) if preds else None

    return render_template('html_mark.html', marks=[mark], show_edit=True, next_page_link=succ_link, prev_page_link=pred_link)
    if self.method == 'GET':
        return self.mark_get(mark)
    if self.method == 'POST':
        return self.mark_post(mark)


@bp.route('/<user>/tags')
def taglist_view(user):
    tags = g.db.get_tags()
    return render_template('html_tags.html', current_tag='tags', tags=tags)


@bp.route('/<user>/search')
def search_view(user):
    query = request.args.get("q")
    if not query:
        redirect(url_for_current_user('.list_view'), 303)

    marks = g.db.get_marks()
    try:
        search = SearchStrParser(query)
    except SearchStrParser.ParsingError as e:
        abort(400, f"Could not parse search string: {query!r}: {e.explanation}")

    def contains(needle, mark):
        if needle.startswith('tag:'):
            return needle[4:] in mark.tags
        else:
            return mark.contains(needle)
    marks = [m
             for m in marks
             if search.evaluate(callback=lambda needle: contains(needle, m))]
    return render_template('html_mark.html', title="[ search results ]", marks=marks)


#################
# Modifying views
#################

@bp.route('/<user>/new', defaults={'mark_id': None})
@bp.route('/<user>/mark.<int:mark_id>/edit')
def new_edit_view(user, mark_id):
    if mark_id is None:
        title = request.args.get('title', '')
        url = request.args.get('url', '') or request.args.get('href', '')
        note = request.args.get('note', '')
        mark = tagbase.Bookmark(title=title, url=url)
    else:
        mark = g.db.lookup(mark_id)
        if not mark:
            raise abort(404, "Bookmark not found")

    return render_template(
        "html_editform.html",
        mark=mark,
        same_url_marks=g.db.get_marks(url=mark.url, not_mark_id=mark.id),
        similar_marks=g.db.find_similar(mark),
        all_tags=[t.name for t in g.db.get_tags(sort_by_frequency=True)],
    )


@bp.route('/<user>/new', defaults={'mark_id': None}, methods=['POST'])
@bp.route('/<user>/mark.<int:mark_id>/edit', methods=['POST'])
def new_edit_post_view(user, mark_id):
    title = request.form.get('title')
    url = request.form.get('url')
    tags = request.form.get('tags')
    note = request.form.get('note')
    if not all([title, url, tags]):
        abort(400, "Title, URL, and tags are necessary.")

    if mark_id is None:
        mark_id = g.db.add(title, url, note, tags)
        if mark_id is None:
            abort(500, "Could not add bookmark")
    else:
        mark = g.db.lookup(mark_id)
        if not mark:
            raise abort(404, "Bookmark not found")
        g.db.edit(mark, title=title, url=url, note=note, tags=tags)

    return redirect(url_for_current_user('.mark_view', mark_id=mark_id))


@bp.route('/<user>/mark.<int:mark_id>/delete', methods=['POST'])
def delete_view(user, mark_id):
    mark = g.db.lookup(mark_id)
    if not mark:
        raise abort(404, "Bookmark not found")
    g.db.delete(mark)
    return render_template('html_delete.html')


###############
# Miscellaneous
###############

@bp.route('/<user>/mark.<int:mark_id>/similar')
def similar_view(user, mark_id):
    mark = g.db.lookup(mark_id)
    if not mark:
        raise abort(404, "Bookmark not found")

    similar = g.db.find_similar(mark)
    return render_template('similar.html', similar_marks=similar)


@bp.route('/<user>/export.xml')
def export_view(user):
    marks = g.db.get_marks()
    return render_template('xml_export.xml', marks=marks)
