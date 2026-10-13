#!/usr/bin/env python3
"""Stable SSH/terminal entry for board-side camera control.

Implementation is split into camera_control/. Command names, stdin JSON,
systemd entry and deployment root remain unchanged.
"""

import sys
from camera_control.cli import main

if __name__ == "__main__":
    sys.exit(main())
