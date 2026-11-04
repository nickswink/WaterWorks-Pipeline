#!/usr/bin/env python3
"""AquaHistorian 4.2 - web server entry point (waitress WSGI)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from waitress import serve  # noqa: E402

from common import load_config  # noqa: E402
from webapp import create_app  # noqa: E402


def main():
    cfg = load_config()
    app = create_app()
    serve(app,
          host=cfg.get("server", "listen"),
          port=cfg.getint("server", "port"),
          threads=cfg.getint("server", "threads"),
          ident="AquaHistorian/%s" % cfg.get("product", "version"))


if __name__ == "__main__":
    main()
