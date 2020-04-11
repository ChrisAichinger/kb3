#
# Slasti -- Templating engine and templates
#
# Copyright (C) 2012-2020 Christian Aichinger
# See file COPYING for licensing information (expect GPL 2).
#

import os
import time

from jinja2 import Environment, PackageLoader, select_autoescape


def format_date(mark_time):
    return time.strftime('%Y-%m-%d', time.gmtime(mark_time))


def render(filename, render_args):
    env = Environment(
        loader=PackageLoader('slasti', 'templates'),
        autoescape=select_autoescape(['html', 'xml'])
    )
    env.filters['format_date'] = format_date
    template = env.get_template(filename)
    return template.render(**render_args)
