"""Parse user commands, read stdin JSON, print one JSON result."""

import argparse
import json
import sys
from .config import ACTIONS, ControlError, validate_config
from .transport import request, serve


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=list(ACTIONS) + ["_serve"])
    parser.add_argument(
        "--config-stdin", action="store_true", help="Read configuration JSON from stdin; start only"
    )
    parser.add_argument("--lines", type=int, default=40)
    args = parser.parse_args()
    if args.action == "_serve":
        serve()
        return 0
    try:
        payload = {"lines": args.lines} if args.action == "logs" else {}
        if args.config_stdin:
            if args.action != "start":
                raise ControlError("--config-stdin is only supported for start")
            payload["config"] = validate_config(json.load(sys.stdin))
        response = request(args.action, payload)
    except Exception as error:
        response = {"ok": False, "error": str(error)}
    print(json.dumps(response, ensure_ascii=False))
    return 0 if response["ok"] else 1
