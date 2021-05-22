#!/usr/bin/python3

import sys
import os
sys.path.append(os.path.dirname(__file__))

from kb3 import create_app
application = create_app()
