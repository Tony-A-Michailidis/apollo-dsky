"""`python -m dsky` or `dsky`: start the DSKY web interface."""

from __future__ import annotations

import argparse


def main() -> None:
    p = argparse.ArgumentParser(prog="dsky", description="Apollo DSKY simulator web interface")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true", help="auto-reload on code changes (development)")
    args = p.parse_args()

    import uvicorn

    uvicorn.run("dsky.server:app", host=args.host, port=args.port, reload=args.reload, log_level="info")


if __name__ == "__main__":
    main()
