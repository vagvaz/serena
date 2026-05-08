import json
import logging
import socket
import threading
from concurrent.futures import Future, TimeoutError
from queue import Queue
from typing import Any

from .dap_protocol import content_length, make_dap_request, parse_dap_message

log = logging.getLogger(__name__)


class DapClient:
    """Real DAP client that connects to the multiplexer over TCP.

    Each instance opens a TCP socket to the multiplexer, sends DAP requests,
    and receives responses and events. This makes the agent appear as a
    normal DAP client to the multiplexer, with its own ``client_id`` and
    full driver/eavesdropper enforcement.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self._host = host
        self._port = port
        self._sock: socket.socket | None = None
        self._seq = 0
        self._seq_lock = threading.Lock()
        self._futures: dict[int, Future] = {}
        self._futures_lock = threading.Lock()
        self._buffer = b""
        self._running = False
        self._reader_thread: threading.Thread | None = None
        self._events: Queue[dict[str, Any]] = Queue()
        self._initialize_done = threading.Event()

    def connect(self, host: str | None = None, port: int | None = None) -> None:
        if host is not None:
            self._host = host
        if port is not None:
            self._port = port
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.connect((self._host, self._port))
        self._running = True
        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True, name="dap-client-reader")
        self._reader_thread.start()

    def close(self) -> None:
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        with self._futures_lock:
            for future in self._futures.values():
                future.set_exception(Exception("Client closed"))
            self._futures.clear()

    def send_request(self, command: str, arguments: Any = None, timeout: float = 30.0) -> dict[str, Any]:
        """Send a DAP request and wait for the response."""
        seq = self._next_seq()
        msg = make_dap_request(command, seq, arguments)
        future: Future = Future()
        with self._futures_lock:
            self._futures[seq] = future
        self._send(msg)
        try:
            result = future.result(timeout=timeout)
            return result
        except TimeoutError:
            with self._futures_lock:
                self._futures.pop(seq, None)
            return {"success": False, "message": f"Request timed out after {timeout}s"}
        except Exception as e:
            with self._futures_lock:
                self._futures.pop(seq, None)
            return {"success": False, "message": str(e)}

    def send_initialize(self, adapter_id: str = "python", timeout: float = 30.0) -> dict[str, Any]:
        """Send the DAP initialize request with standard client info."""
        result = self.send_request("initialize", {
            "clientID": "serena-agent",
            "clientName": "Serena Agent",
            "adapterID": adapter_id,
            "pathFormat": "path",
            "linesStartAt1": True,
            "columnsStartAt1": True,
            "supportsVariableType": True,
            "supportsRunInTerminalRequest": True,
            "locale": "en-us",
        }, timeout=timeout)
        if result.get("success"):
            self._initialize_done.set()
        return result

    def wait_for_initialize(self, timeout: float = 5.0) -> bool:
        return self._initialize_done.wait(timeout=timeout)

    def get_event(self, timeout: float = 1.0) -> dict[str, Any] | None:
        """Get the next buffered event, or None if none available."""
        try:
            return self._events.get(timeout=timeout)
        except Exception:
            return None

    def wait_for_stopped(self, timeout: float = 0.5) -> dict[str, Any] | None:
        """Wait briefly for a ``stopped`` event and return its body, or None."""
        event = self.get_event(timeout=timeout)
        if event and event.get("event") == "stopped":
            return event.get("body") or {}
        return None

    def await_stop(self, timeout: float = 30.0) -> dict[str, Any] | None:
        """Block until a ``stopped`` event arrives, discarding other events.
        Returns the event body, or ``None`` on timeout.
        """
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            event = self.get_event(timeout=min(remaining, 1.0))
            if event is None:
                continue
            if event.get("event") == "stopped":
                return event.get("body") or {}
            log.debug("await_stop: discarding event %s", event.get("event"))
        return None

    def discarding_events(self) -> None:
        """Discard all buffered events (e.g. after establishing initial state)."""
        while not self._events.empty():
            try:
                self._events.get_nowait()
            except Exception:
                break

    def _next_seq(self) -> int:
        with self._seq_lock:
            self._seq += 1
            return self._seq

    def _recv_all(self, n: int) -> bytes:
        data = b""
        assert self._sock is not None
        while len(data) < n:
            chunk = self._sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("Connection closed while reading")
            data += chunk
        return data

    def _read_loop(self) -> None:
        partial = b""
        while self._running:
            try:
                if self._sock is None:
                    break
                chunk = self._sock.recv(4096)
                if not chunk:
                    log.info("DAP client connection closed by server")
                    break
                partial += chunk
                while True:
                    consumed = self._try_process_message(partial)
                    if consumed == 0:
                        break
                    partial = partial[consumed:]
            except (ConnectionResetError, BrokenPipeError, OSError) as e:
                if self._running:
                    log.warning("DAP client connection error: %s", e)
                break
        self._running = False

    def _try_process_message(self, data: bytes) -> int:
        try:
            header_end = data.index(b"\r\n\r\n")
        except ValueError:
            return 0
        header_part = data[:header_end]
        body_start = header_end + 4

        num_bytes = None
        for line in header_part.split(b"\r\n"):
            n = content_length(line)
            if n is not None:
                num_bytes = n
                break
        if num_bytes is None:
            return 0

        total_len = body_start + num_bytes
        if len(data) < total_len:
            return 0

        body = data[body_start:total_len]
        try:
            msg = parse_dap_message(body)
        except json.JSONDecodeError:
            log.error("DAP client: failed to parse message: %s", body[:200])
            return total_len

        self._dispatch_message(msg)
        return total_len

    def _dispatch_message(self, msg: dict[str, Any]) -> None:
        msg_type = msg.get("type")
        if msg_type == "response":
            request_seq = msg.get("request_seq")
            with self._futures_lock:
                future = self._futures.pop(request_seq, None)
            if future is not None:
                future.set_result(msg)
            else:
                log.warning("DAP client: response for unknown request_seq %s", request_seq)
        elif msg_type == "event":
            self._events.put(msg)
        elif msg_type == "request":
            log.debug("DAP client: received request from server (not handled): %s", msg.get("command"))

    def _send(self, msg: dict[str, Any]) -> None:
        if self._sock is None:
            return
        body = json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
        try:
            self._sock.sendall(header + body)
        except OSError as e:
            log.error("DAP client: failed to send: %s", e)
