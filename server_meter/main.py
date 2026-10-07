"""Process entrypoint: load YAML, validate, start Uvicorn, handle signals."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
from pathlib import Path

import uvicorn

from server_meter.app import create_app
from server_meter.config import ConfigError, load_config
from server_meter.logging_config import configure_logging

logger = logging.getLogger("server_meter")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="server-meter", description="RAM-only BME690 monitor")
    parser.add_argument("--config", dest="config", help="Path to YAML configuration")
    parser.add_argument("--host", dest="host", help="Override web.host")
    parser.add_argument("--port", dest="port", type=int, help="Override web.port")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        sys.stderr.write(f"server-meter configuration error: {exc}\n")
        return 2

    if args.host:
        config.web.host = args.host
    if args.port:
        config.web.port = args.port

    configure_logging(config)
    logger.info(
        "starting %s env=%s driver=%s listen=%s:%s (history is RAM-only)",
        config.application.name,
        config.application.environment,
        config.sensor.driver,
        config.web.host,
        config.web.port,
    )

    app = create_app(config)
    common = {
        "app": app,
        "host": config.web.host,
        "port": config.web.port,
        "log_config": None,
        "access_log": config.logging.access_log,
        "timeout_keep_alive": 10,
        "proxy_headers": True,
        "server_header": False,
    }
    try:
        uv_config = uvicorn.Config(
            **common,
            timeout_graceful_shutdown=12,
            date_header=False,
        )
    except TypeError:
        uv_config = uvicorn.Config(**common)
    server = uvicorn.Server(uv_config)

    def _signal(signum: int, _frame: object) -> None:
        logger.info("received signal %s; shutting down (no disk writes)", signum)
        server.should_exit = True

    signal.signal(signal.SIGTERM, _signal)
    signal.signal(signal.SIGINT, _signal)

    try:
        server.run()
    except OSError as exc:
        logger.error("HTTP server failed: %s", exc)
        return 1
    logger.info("server-meter stopped")
    return 0


def config_path_hint() -> Path:
    return Path("/etc/server-meter/config.yaml")


if __name__ == "__main__":
    raise SystemExit(main())
