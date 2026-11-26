#!/usr/bin/env python3
"""Single entry point for the CLI and daemon."""
from __future__ import annotations

import sys


def main():
    if len(sys.argv) > 1 and sys.argv[1] == 'run-daemon':
        from wavedpi.core import serve
        serve()
        return
    from wavedpi.cli import main as cli
    cli(sys.argv[1:])


if __name__ == '__main__':
    main()
