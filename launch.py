#!/usr/bin/env python3
"""Cross-platform Wave DPI entry point."""
from __future__ import annotations

import os
import sys


def main():
    if os.name == 'nt':
        from wavedpi.win_cli import main as windows_main
        windows_main(sys.argv[1:])
        return
    if len(sys.argv) > 1 and sys.argv[1] == 'run-daemon':
        from wavedpi.core import serve
        serve()
        return
    from wavedpi.cli import main as linux_main
    linux_main(sys.argv[1:])


if __name__ == '__main__':
    main()
