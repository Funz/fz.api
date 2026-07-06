"""Command-line entry point: ``fz-api`` runs the server via uvicorn."""

import argparse

from . import __version__


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="fz-api", description="Serve the fz HTTP API"
    )
    parser.add_argument("--version", action="version", version=f"fz-api {__version__}")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Auto-reload (development)")
    parser.add_argument(
        "--workers", type=int, default=1, help="Number of worker processes (default: 1)"
    )
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(
        "fz_api.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=args.workers,
    )


if __name__ == "__main__":
    main()
