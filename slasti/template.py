#
# Slasti -- Templating engine and templates
#
# Copyright (C) 2012-2013 Christian Aichinger
# See file COPYING for licensing information (expect GPL 2).
#

import os

from mako.template import Template as makoTemplate
from mako.lookup import TemplateLookup

class Filter:
    @staticmethod
    def html(str):
        str = str.replace("&", "&amp;")
        str = str.replace("<", "&lt;")
        str = str.replace(">", "&gt;")
        str = str.replace('"', "&quot;")
        str = str.replace("'", "&#x27;")
        str = str.replace("/", "&#x2F;")
        return str

    @staticmethod
    def attr(str):
        no_escape = "abcdefghijklmnopqrstuvwxyz" + \
                    "ABCDEFGHIJKLMNOPQRSTUVWXYZ" + \
                    "0123456789"
        result = []
        for char in str:
            if char in no_escape:
                result.append(char)
                continue
            result.append("&#{};".format(ord(char)))

        return ''.join(result)

def render(filename, render_args):
    slasti_dir = os.path.dirname(os.path.abspath(__file__))
    template_dir = os.path.join(slasti_dir, "templates")

    template = makoTemplate(filename=os.path.join(template_dir, filename),
                        lookup=TemplateLookup(directories=['.', template_dir]),
                        output_encoding="utf-8")
    render_args.setdefault("filter", Filter)
    return template.render(**render_args)

