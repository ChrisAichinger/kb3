import os
import json

from flask import Flask


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    if test_config is None:
        app.config.from_pyfile('config.py')
    else:
        app.config.from_mapping(test_config)

    assert os.path.isdir(app.instance_path)
    with open(app.config['SLASTI_USERS_FILE']) as f:
        app.config['SLASTI_USERS'] = {u['name']: u for u in json.load(f)}

    from . import bookmarks
    app.register_blueprint(bookmarks.bp)
    app.add_url_rule('/', endpoint='index')

    if app.config.get('PROFILE'):
        from wsgi_lineprof.middleware import LineProfilerMiddleware
        from wsgi_lineprof.filters import FilenameFilter, TotalTimeSorter
        filters = [FilenameFilter(r"__init__.py|bookmarks.py|tagbase.py", regex=True), TotalTimeSorter()]
        app = LineProfilerMiddleware(app, filters=filters)

    return app
