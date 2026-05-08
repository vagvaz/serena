import json
import logging
import socket
import threading
from collections.abc import Callable
from concurrent.futures import Future
from http.server import BaseHTTPRequestHandler, HTTPServer
from queue import Empty, Queue
from typing import Any

from .adapter_config import AdapterConfig, DebugAdapterLanguage
from .dap_protocol import (
    MUTATING_COMMANDS,
    ALWAYS_ALLOWED_COMMANDS,
    content_length,
    make_dap_error_response,
    make_dap_event,
    make_dap_request,
    make_dap_response,
    parse_dap_message,
)
from .debug_adapter import DebugAdapterProcess
from .session_manager import DebugSessionManager

CONTROL_MUTATING = "mutating"
CONTROL_ALWAYS = "always"
CONTROL_READONLY = "readonly"

log = logging.getLogger(__name__)

DRIVER_AGENT = -1


class Multiplexer:
    def __init__(
        self,
        adapter_config: AdapterConfig,
        language: DebugAdapterLanguage,
        session_manager: DebugSessionManager | None = None,
        project_name: str = "default",
        handoff_port: int = 0,
    ) -> None:
        self._adapter_config = adapter_config
        self._language = language
        self._session_manager = session_manager
        self._project_name = project_name
        self._handoff_port = handoff_port

        self._lock = threading.Lock()
        self._adapter: DebugAdapterProcess | None = None
        self._tcp_port: int = 0
        self._tcp_server_socket: socket.socket | None = None
        self._http_server: HTTPServer | None = None
        self._running = False

        self._clients: dict[int, "ClientConnection"] = {}
        self._next_client_id = 1
        self._driver_client_id: int | None = None
        # client_id -> {source_path -> {line_numbers}}
        self._client_breakpoints: dict[int, dict[str, set[int]]] = {}
        self._adapter_breakpoint_sources: dict[str, int] = {}
        """Tracks which adapter seq has pending breakpoints per source."""

        self._adapter_seq_counter = 0
        self._seq_map: dict[int, tuple[int, int, str]] = {}
        self._adapter_msg_queue: Queue[dict[str, Any]] = Queue()

        self._shutdown_event = threading.Event()
        self._http_ready_event = threading.Event()

        self._tool_futures: dict[int, Future] = {}
        self._tool_futures_lock = threading.Lock()

    @property
    def tcp_port(self) -> int:
        return self._tcp_port

    @property
    def is_driver_agent(self) -> bool:
        with self._lock:
            return self._driver_client_id == DRIVER_AGENT

    def start(self, tcp_host: str = "127.0.0.1", tcp_port: int = 0) -> int:
        self._tcp_server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._tcp_server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._tcp_server_socket.bind((tcp_host, tcp_port))
        self._tcp_server_socket.listen(5)
        self._tcp_port = self._tcp_server_socket.getsockname()[1]
        self._running = True

        threading.Thread(target=self._http_server_thread, daemon=True, name="mux-http").start()
        self._http_ready_event.wait(timeout=5)
        threading.Thread(target=self._accept_clients, daemon=True, name="mux-accept").start()
        threading.Thread(target=self._dispatch_thread, daemon=True, name="mux-dispatch").start()

        log.info(
            "Multiplexer started: TCP=%s:%d, HTTP port=%d",
            tcp_host, self._tcp_port, self._handoff_port,
        )
        return self._tcp_port

    def stop(self) -> None:
        self._running = False
        self._shutdown_event.set()

        if self._http_server:
            try:
                self._http_server.shutdown()
            except Exception:
                pass
            self._http_server = None

        if self._tcp_server_socket:
            try:
                self._tcp_server_socket.close()
            except Exception:
                pass
            self._tcp_server_socket = None

        with self._lock:
            for client in list(self._clients.values()):
                client.close()
            self._clients.clear()

        if self._adapter:
            try:
                self._adapter.stop()
            except Exception:
                pass
            self._adapter = None

        log.info("Multiplexer stopped")

    def start_adapter(self) -> None:
        if self._adapter:
            return
        adapter = DebugAdapterProcess(
            adapter_config=self._adapter_config,
            language=self._language,
            on_message=self._on_adapter_message,
            on_error=self._on_adapter_error,
        )
        adapter.start()
        self._adapter = adapter

    def stop_adapter(self) -> None:
        with self._lock:
            adapter = self._adapter
            self._adapter = None
        if adapter:
            adapter.stop()

    def handoff_to_agent(self) -> str:
        with self._lock:
            self._driver_client_id = DRIVER_AGENT
        self._broadcast_event("window/showMessage", {
            "type": 3,
            "message": "Agent now has control of the debug session. The agent can step, continue, and inspect state.",
        })
        log.info("Driver handed off to agent")
        return "Driver handed off to agent"

    def handoff_to_human(self) -> str:
        with self._lock:
            old_driver = self._driver_client_id
            for cid in list(self._clients.keys()):
                self._driver_client_id = cid
                break
            if self._driver_client_id is None or self._driver_client_id == DRIVER_AGENT:
                self._driver_client_id = None
            else:
                if old_driver is not None and old_driver in self._client_breakpoints:
                    self._clear_client_breakpoints_locked(old_driver)
        log.info(
            "Driver handed back to human (was driver=%s, now=%s)",
            old_driver, self._driver_client_id,
        )
        return "Driver handed back to human"

    def get_all_client_breakpoints(self) -> dict[int, dict[str, list[int]]]:
        with self._lock:
            return {
                cid: {src: sorted(lines) for src, lines in sources.items()}
                for cid, sources in self._client_breakpoints.items()
            }

    def send_adapter_message(self, msg: dict[str, Any]) -> None:
        if self._adapter:
            self._adapter.send_message(msg)

    def send_request_and_wait(
        self, command: str, arguments: Any = None, timeout: float = 30.0
    ) -> dict[str, Any]:
        adapter_seq = self._next_adapter_seq()
        future: Future = Future()
        with self._tool_futures_lock:
            self._tool_futures[adapter_seq] = future
        req = make_dap_request(command, adapter_seq, arguments)
        self.send_adapter_message(req)
        try:
            result = future.result(timeout=timeout)
            return result
        except TimeoutError:
            with self._tool_futures_lock:
                self._tool_futures.pop(adapter_seq, None)
            return {"success": False, "message": f"Request timed out after {timeout}s"}
        except Exception as e:
            with self._tool_futures_lock:
                self._tool_futures.pop(adapter_seq, None)
            return {"success": False, "message": str(e)}

    def _accept_clients(self) -> None:
        while self._running:
            try:
                conn, addr = self._tcp_server_socket.accept()
                log.info("Client connected from %s:%s", *addr)
                client_id = self._next_client_id
                self._next_client_id += 1
                client = ClientConnection(conn, client_id, addr)
                with self._lock:
                    self._clients[client_id] = client
                    if self._driver_client_id is None:
                        self._driver_client_id = client_id
                        log.info("First client %d is now driver", client_id)
                threading.Thread(
                    target=self._client_read_thread,
                    args=(client,),
                    daemon=True,
                    name=f"mux-client-{client_id}",
                ).start()
            except OSError:
                if not self._running:
                    break
                log.exception("Error accepting client")

    def _client_read_thread(self, client: "ClientConnection") -> None:
        partial = b""
        while self._running and client.is_open():
            try:
                data = client.read_some(4096)
                if not data:
                    break
                partial += data
                while True:
                    msg_or_none, consumed = self._try_extract_message(partial)
                    if msg_or_none is None:
                        break
                    partial = partial[consumed:]
                    self._handle_client_message(client, msg_or_none)
            except (ConnectionResetError, BrokenPipeError, OSError):
                break
        self._client_disconnected(client)

    def _try_extract_message(self, data: bytes) -> tuple[dict[str, Any] | None, int]:
        try:
            header_end = data.index(b"\r\n\r\n")
        except ValueError:
            return None, 0
        header_part = data[:header_end]
        body_start = header_end + 4

        num_bytes = None
        for line in header_part.split(b"\r\n"):
            n = content_length(line)
            if n is not None:
                num_bytes = n
                break
        if num_bytes is None:
            return None, 0

        total_len = body_start + num_bytes
        if len(data) < total_len:
            return None, 0

        body = data[body_start:total_len]
        try:
            msg = parse_dap_message(body)
        except json.JSONDecodeError:
            log.error("Failed to parse DAP message: %s", body[:200])
            return None, total_len
        return msg, total_len

    def _handle_client_message(self, client: "ClientConnection", msg: dict[str, Any]) -> None:
        msg_type = msg.get("type")
        if msg_type != "request":
            log.warning("Ignoring non-request from client %d: type=%s", client.client_id, msg_type)
            return

        command = msg.get("command", "")
        arguments = msg.get("arguments")
        client_seq = msg.get("seq", 0)

        control_type = self._get_control_type(command)

        if control_type == CONTROL_MUTATING:
            with self._lock:
                is_driver = (self._driver_client_id == client.client_id or
                             (DRIVER_AGENT == self._driver_client_id and client.client_id != DRIVER_AGENT))
            if not is_driver:
                err = make_dap_error_response(
                    client_seq, command, self._next_seq(),
                    f"Only the driver can send '{command}'. The agent currently has control."
                    if self.is_driver_agent else
                    f"Only the driver can send '{command}'.",
                )
                client.send_message(err)

                if not self.is_driver_agent and self._driver_client_id == client.client_id:
                    pass
                elif not self.is_driver_agent:
                    err_msg = "You do not have driver control. Use the agent to request control or ask the driver."
                    log.info("Non-driver client %d tried %s", client.client_id, command)
                return

            if not self.is_driver_agent and client.client_id != self._driver_client_id:
                pass

            if self.is_driver_agent and client.client_id != DRIVER_AGENT:
                self._handle_human_reclaim(client, command)

        elif control_type == CONTROL_ALWAYS:
            pass

        elif control_type == CONTROL_READONLY:
            if command == "setBreakpoints":
                self._record_client_breakpoints(client.client_id, arguments)

        adapter_seq = self._next_adapter_seq()
        with self._lock:
            self._seq_map[adapter_seq] = (client.client_id, client_seq, command)

        req = make_dap_request(command, adapter_seq, arguments)
        self.send_adapter_message(req)

    def _get_control_type(self, command: str) -> str:
        if command in MUTATING_COMMANDS:
            return CONTROL_MUTATING
        if command in ALWAYS_ALLOWED_COMMANDS:
            return CONTROL_ALWAYS
        return CONTROL_READONLY

    def _record_client_breakpoints(self, client_id: int, arguments: Any) -> None:
        if not arguments:
            return
        source = arguments.get("source") or {}
        source_path = source.get("path", "")
        bps = arguments.get("breakpoints", [])
        with self._lock:
            if client_id not in self._client_breakpoints:
                self._client_breakpoints[client_id] = {}
            if not bps or not source_path:
                self._client_breakpoints[client_id].pop(source_path, None)
            else:
                if source_path not in self._client_breakpoints[client_id]:
                    self._client_breakpoints[client_id][source_path] = set()
                self._client_breakpoints[client_id][source_path] = {bp.get("line", 0) for bp in bps}

    def _clear_client_breakpoints_locked(self, client_id: int, seq: int = 0) -> None:
        """Clear breakpoints for a client and send empty setBreakpoints to the adapter.
        Caller must hold ``_lock``. Pass *seq* if caller already allocated one,
        otherwise pass 0 to allocate one here (but then caller must NOT hold ``_lock``).
        """
        sources = self._client_breakpoints.pop(client_id, None)
        if not sources:
            return
        for source_path, lines in sources.items():
            if not source_path:
                continue
            adapter_seq = seq if seq else self._adapter_seq_counter + 1
            if not seq:
                self._adapter_seq_counter += 1
            req = make_dap_request("setBreakpoints", adapter_seq, {
                "source": {"path": source_path},
                "breakpoints": [],
            })
            log.info(
                "Clearing %d breakpoint(s) for client %d at %s: %s",
                len(lines), client_id, source_path, sorted(lines),
            )
            self.send_adapter_message(req)

    def _handle_human_reclaim(self, client: "ClientConnection", command: str) -> None:
        old_driver: int | None = None
        with self._lock:
            old_driver = self._driver_client_id
            self._driver_client_id = client.client_id
            if old_driver is not None and old_driver in self._client_breakpoints:
                self._clear_client_breakpoints_locked(old_driver)
        log.info("Human reclaimed driver (client %d sent %s)", client.client_id, command)
        self._broadcast_event("window/showMessage", {
            "type": 3,
            "message": "Human has reclaimed driver control. Previous driver's breakpoints cleared.",
        })

    def _on_adapter_message(self, msg: dict[str, Any]) -> None:
        self._adapter_msg_queue.put(msg)

    def _on_adapter_error(self, exception: Exception) -> None:
        log.error("Adapter error: %s", exception)
        self._broadcast_event("window/showMessage", {
            "type": 1,
            "message": f"Debug adapter error: {exception}",
        })

    def _dispatch_thread(self) -> None:
        while self._running:
            try:
                msg = self._adapter_msg_queue.get(timeout=0.5)
            except Empty:
                if self._shutdown_event.is_set():
                    break
                continue

            msg_type = msg.get("type")
            if msg_type == "event":
                self._broadcast(msg)
            elif msg_type == "response":
                self._route_response(msg)
            elif msg_type == "request":
                self._broadcast(msg)
            else:
                log.warning("Unknown adapter message type: %s", msg_type)

    def _route_response(self, msg: dict[str, Any]) -> None:
        request_seq = msg.get("request_seq")

        with self._tool_futures_lock:
            tool_future = self._tool_futures.pop(request_seq, None)
        if tool_future is not None:
            tool_future.set_result(msg)
            return

        with self._lock:
            entry = self._seq_map.pop(request_seq, None)
        if entry is None:
            log.warning("No pending request for adapter seq %s", request_seq)
            return

        client_id, client_seq, command = entry
        response = make_dap_response(
            request_seq=client_seq,
            command=command,
            seq=self._next_seq(),
            body=msg.get("body"),
            success=msg.get("success", True),
            message=msg.get("message"),
        )

        with self._lock:
            client = self._clients.get(client_id)
        if client:
            client.send_message(response)
        else:
            log.warning("Client %d disconnected before response", client_id)

    def _broadcast(self, msg: dict[str, Any]) -> None:
        with self._lock:
            clients = list(self._clients.values())
        for client in clients:
            try:
                client.send_message(msg)
            except Exception:
                log.exception("Error broadcasting to client %d", client.client_id)

    def _broadcast_event(self, event: str, body: dict[str, Any]) -> None:
        self._broadcast(make_dap_event(event, self._next_seq(), body))

    def _client_disconnected(self, client: "ClientConnection") -> None:
        with self._lock:
            self._clear_client_breakpoints_locked(client.client_id)
            self._clients.pop(client.client_id, None)
            if self._driver_client_id == client.client_id:
                self._driver_client_id = None
                for remaining_id in list(self._clients.keys()):
                    self._driver_client_id = remaining_id
                    break
                log.info(
                    "Driver client %d disconnected. New driver: %s",
                    client.client_id, self._driver_client_id,
                )
        client.close()

    def _next_adapter_seq(self) -> int:
        with self._lock:
            self._adapter_seq_counter += 1
            return self._adapter_seq_counter

    def _next_seq(self) -> int:
        return self._next_adapter_seq()

    def _http_server_thread(self) -> None:
        class HandoffHandler(BaseHTTPRequestHandler):
            multiplexer: "Multiplexer" = None

            def log_message(self, fmt: str, *args: Any) -> None:
                log.debug("HTTP handoff: " + fmt, *args)

            def do_GET(self) -> None:
                if self.path.startswith("/handoff"):
                    params = self._parse_params()
                    to = params.get("to", "")
                    if to == "agent":
                        result = self.multiplexer.handoff_to_agent()
                        self._send_json(200, {"status": "ok", "message": result})
                    else:
                        self._send_json(400, {"status": "error", "message": f"Unknown target: {to}"})
                elif self.path == "/health":
                    self._send_json(200, {"status": "ok"})
                elif self.path == "/status":
                    with self.multiplexer._lock:
                        driver = self.multiplexer._driver_client_id
                    self._send_json(200, {
                        "status": "ok",
                        "driver": "agent" if driver == DRIVER_AGENT else f"client_{driver}",
                        "tcp_port": self.multiplexer.tcp_port,
                        "adapter_running": self.multiplexer._adapter is not None and self.multiplexer._adapter.is_running(),
                        "clients": list(self.multiplexer._clients.keys()) if hasattr(self.multiplexer, "_clients") else [],
                    })
                else:
                    self._send_json(404, {"status": "error", "message": "Not found"})

            def _parse_params(self) -> dict[str, str]:
                from urllib.parse import urlparse, parse_qs
                parsed = urlparse(self.path)
                qs = parse_qs(parsed.query)
                return {k: v[0] for k, v in qs.items()}

            def _send_json(self, status: int, data: dict[str, Any]) -> None:
                body = json.dumps(data).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        HandoffHandler.multiplexer = self
        self._http_server = HTTPServer(("127.0.0.1", self._handoff_port), HandoffHandler)
        self._handoff_port = self._http_server.server_address[1]
        log.info("HTTP handoff server listening on port %d", self._handoff_port)
        self._http_ready_event.set()
        self._http_server.serve_forever()

    def get_handoff_port(self) -> int:
        return self._handoff_port


class ClientConnection:
    def __init__(self, sock: socket.socket, client_id: int, addr: tuple[str, int]) -> None:
        self._sock = sock
        self.client_id = client_id
        self._addr = addr
        self._lock = threading.Lock()
        self._closed = False

    def is_open(self) -> bool:
        return not self._closed

    def read_some(self, max_bytes: int = 4096) -> bytes:
        return self._sock.recv(max_bytes)

    def send_message(self, msg: dict[str, Any]) -> None:
        if self._closed:
            return
        body = json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
        with self._lock:
            try:
                self._sock.sendall(header + body)
            except OSError:
                self._closed = True

    def close(self) -> None:
        self._closed = True
        try:
            self._sock.close()
        except Exception:
            pass
