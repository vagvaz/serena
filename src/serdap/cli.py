"""CLI entry point for the serdap-mux binary alias.

When the user's IDE points its debug adapter to ``serdap-mux``, this
module is invoked. It starts the multiplexer TCP server on a configurable
port and waits for DAP client connections (IDE + agent).
"""

import argparse
import logging
import sys
from typing import NoReturn

from .adapter_config import DebugAdapterLanguage, get_adapter_config
from .multiplexer import Multiplexer
from .session_manager import DebugSessionManager

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> NoReturn:
    parser = argparse.ArgumentParser(description="DAP Multiplexer — serdap-mux")
    parser.add_argument(
        "--tcp-host", default="127.0.0.1",
        help="Host to bind the TCP server (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--tcp-port", type=int, default=0,
        help="Port for the TCP server (default: random available port)",
    )
    parser.add_argument(
        "--http-port", type=int, default=0,
        help="Port for the HTTP handoff endpoint (default: random available port)",
    )
    parser.add_argument(
        "--lang", choices=["python", "cpp"], default="python",
        help="Debug adapter language (default: python)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    lang = DebugAdapterLanguage(args.lang)
    adapter_config = get_adapter_config(lang)
    manager = DebugSessionManager()

    mux = Multiplexer(
        adapter_config=adapter_config,
        language=lang,
        session_manager=manager,
        project_name="cli-session",
        handoff_port=args.http_port,
    )
    tcp_port = mux.start(tcp_host=args.tcp_host, tcp_port=args.tcp_port)
    mux.start_adapter()

    print(f"serdap-mux started. TCP port: {tcp_port}, HTTP handoff port: {mux.get_handoff_port()}", flush=True)
    print(f"Connect your IDE debug adapter to tcp://{args.tcp_host}:{tcp_port}", flush=True)
    print(f"Agent handoff: http://127.0.0.1:{mux.get_handoff_port()}/handoff?to=agent", flush=True)

    try:
        import time
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        mux.stop()

    sys.exit(0)
