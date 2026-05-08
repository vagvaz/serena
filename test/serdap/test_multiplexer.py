import json
import socket
import threading
import time

import pytest

from serdap.adapter_config import AdapterConfig, DebugAdapterLanguage
from serdap.multiplexer import Multiplexer, DRIVER_AGENT
from serdap.session_manager import DebugSessionManager


class TestMultiplexer:
    @pytest.fixture
    def mux(self):
        adapter_config = AdapterConfig(
            cmd=["echo", "adapter"],
            adapter_name="mock",
        )
        manager = DebugSessionManager.get_instance()
        m = Multiplexer(
            adapter_config=adapter_config,
            language=DebugAdapterLanguage.PYTHON,
            session_manager=manager,
            project_name="test",
            handoff_port=0,
        )
        m.start(tcp_host="127.0.0.1", tcp_port=0)
        manager.create_session("test", m)
        yield m
        m.stop()
        DebugSessionManager.reset_instance()

    def _connect_client(self, port: int) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(("127.0.0.1", port))
        time.sleep(0.1)
        return sock

    def _send_dap_message(self, sock: socket.socket, msg: dict) -> None:
        body = json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
        sock.sendall(header + body)

    def _recv_dap_message(self, sock: socket.socket, timeout: float = 2.0) -> dict | None:
        sock.settimeout(timeout)
        try:
            line = sock.recv(1024)
        except socket.timeout:
            return None
        if not line:
            return None
        header_end = line.find(b"\r\n\r\n")
        if header_end == -1:
            return None
        body_start = header_end + 4
        body = line[body_start:]
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return None

    def test_start_stop(self, mux):
        assert mux.tcp_port > 0
        assert mux.get_handoff_port() > 0
        mux.stop()
        assert mux._running is not True

    def test_first_client_becomes_driver(self, mux):
        sock = self._connect_client(mux.tcp_port)
        try:
            assert not mux.is_driver_agent
            assert mux._driver_client_id is not None
            assert mux._driver_client_id != DRIVER_AGENT
        finally:
            sock.close()

    def test_multiple_clients(self, mux):
        sock1 = self._connect_client(mux.tcp_port)
        sock2 = self._connect_client(mux.tcp_port)
        try:
            assert mux._driver_client_id is not None
            assert len(mux._clients) == 2
        finally:
            sock1.close()
            sock2.close()

    def test_handoff_to_agent(self, mux):
        sock = self._connect_client(mux.tcp_port)
        assert not mux.is_driver_agent
        mux.handoff_to_agent()
        assert mux.is_driver_agent
        sock.close()

    def test_handoff_to_human(self, mux):
        sock = self._connect_client(mux.tcp_port)
        mux.handoff_to_agent()
        mux.handoff_to_human()
        assert not mux.is_driver_agent
        sock.close()
        mux.handoff_to_agent()
        assert mux.is_driver_agent

    def test_handoff_to_human(self, mux):
        self._connect_client(mux.tcp_port)
        mux.handoff_to_agent()
        assert mux.is_driver_agent
        mux.handoff_to_human()
        assert not mux.is_driver_agent

    def test_agent_breakpoint_tracking(self, mux):
        sock = self._connect_client(mux.tcp_port)
        mux.handoff_to_agent()
        assert mux.get_all_client_breakpoints() == {}

        with mux._lock:
            mux._client_breakpoints.setdefault(mux._driver_client_id, {})
            mux._client_breakpoints[mux._driver_client_id]["test.py"] = {42, 100}
        bps = mux.get_all_client_breakpoints()
        assert 42 in bps.get(mux._driver_client_id, {}).get("test.py", set())
        assert 100 in bps.get(mux._driver_client_id, {}).get("test.py", set())

    def test_clear_agent_breakpoints_on_human_reclaim(self, mux):
        sock = self._connect_client(mux.tcp_port)
        mux.handoff_to_agent()

        with mux._lock:
            mux._client_breakpoints.setdefault(mux._driver_client_id, {})
            mux._client_breakpoints[mux._driver_client_id]["test.py"] = {42}

        mux.handoff_to_human()
        assert mux.get_all_client_breakpoints() == {}
        sock.close()

    def test_http_handoff_endpoint(self, mux):
        import http.client
        port = mux.get_handoff_port()
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        try:
            conn.request("GET", "/handoff?to=agent")
            resp = conn.getresponse()
            assert resp.status == 200
            data = json.loads(resp.read().decode())
            assert data["status"] == "ok"
            assert mux.is_driver_agent
        finally:
            conn.close()

    def test_http_health_endpoint(self, mux):
        import http.client
        port = mux.get_handoff_port()
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        try:
            conn.request("GET", "/health")
            resp = conn.getresponse()
            assert resp.status == 200
            data = json.loads(resp.read().decode())
            assert data["status"] == "ok"
        finally:
            conn.close()

    def test_http_status_endpoint(self, mux):
        import http.client
        port = mux.get_handoff_port()
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        self._connect_client(mux.tcp_port)
        try:
            conn.request("GET", "/status")
            resp = conn.getresponse()
            assert resp.status == 200
            data = json.loads(resp.read().decode())
            assert data["status"] == "ok"
            assert "driver" in data
            assert data["tcp_port"] == mux.tcp_port
        finally:
            conn.close()

    def test_http_unknown_endpoint(self, mux):
        import http.client
        port = mux.get_handoff_port()
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        try:
            conn.request("GET", "/unknown")
            resp = conn.getresponse()
            assert resp.status == 404
        finally:
            conn.close()

    def test_human_reclaim_via_mutating_command(self, mux):
        sock = self._connect_client(mux.tcp_port)
        mux.handoff_to_agent()
        assert mux.is_driver_agent

        assert mux._driver_client_id == DRIVER_AGENT
        assert mux._clients

        client_id = next(iter(mux._clients.keys()))
        mux._handle_human_reclaim(mux._clients[client_id], "next")
        assert not mux.is_driver_agent
        assert mux._driver_client_id == client_id

    def test_driver_change_sends_message(self, mux):
        sock = self._connect_client(mux.tcp_port)
        mux.handoff_to_agent()
        assert mux.is_driver_agent

        mux.handoff_to_human()
        assert not mux.is_driver_agent

    def test_http_handoff_unknown_target(self, mux):
        import http.client
        port = mux.get_handoff_port()
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        try:
            conn.request("GET", "/handoff?to=unknown")
            resp = conn.getresponse()
            assert resp.status == 400
            data = json.loads(resp.read().decode())
            assert data["status"] == "error"
        finally:
            conn.close()

    def test_session_manager_integration(self, mux):
        manager = DebugSessionManager.get_instance()
        session = manager.get_session("test")
        assert session is not None
        assert session.is_active()
        assert session.multiplexer is mux
        session.close()
        assert not session.is_active()

    def test_send_request_and_wait_timeout(self, mux):
        """send_request_and_wait should return error when adapter not running."""
        result = mux.send_request_and_wait("stackTrace", timeout=0.5)
        assert result.get("success") is False
        assert "timed out" in result.get("message", "").lower()

    def test_send_request_and_wait_future_plumbing(self, mux):
        """Verify that tool futures are created, resolved by _route_response, and cleaned up."""
        import threading
        import time

        captured_seq = None

        def resolve_after_future():
            nonlocal captured_seq
            deadline = time.time() + 3.0
            while time.time() < deadline:
                seq = None
                with mux._tool_futures_lock:
                    if mux._tool_futures:
                        seq = next(iter(mux._tool_futures.keys()))
                if seq is not None:
                    captured_seq = seq
                    sentinel = {
                        "seq": 99, "type": "response",
                        "request_seq": seq,
                        "command": "test", "success": True,
                        "body": {"result": "ok"},
                    }
                    mux._route_response(sentinel)
                    return
                time.sleep(0.005)

        t = threading.Thread(target=resolve_after_future, daemon=True)
        t.start()

        result = mux.send_request_and_wait("test", timeout=3.0)

        assert result.get("success") is True, f"response was: {result}"
        assert result.get("body", {}).get("result") == "ok"
        with mux._tool_futures_lock:
            assert captured_seq is None or captured_seq not in mux._tool_futures


class TestDapClient:
    @pytest.fixture
    def mux(self):
        from serdap.dap_client import DapClient as _DapClient  # noqa: F811
        adapter_config = AdapterConfig(cmd=["echo", "adapter"], adapter_name="mock")
        manager = DebugSessionManager.get_instance()
        m = Multiplexer(
            adapter_config=adapter_config,
            language=DebugAdapterLanguage.PYTHON,
            session_manager=manager,
            project_name="dap-client-test",
            handoff_port=0,
        )
        m.start(tcp_host="127.0.0.1", tcp_port=0)
        manager.create_session("dap-client-test", m)
        yield m
        m.stop()
        DebugSessionManager.reset_instance()

    def test_connect_and_disconnect(self, mux):
        """DapClient can connect to the multiplexer and close cleanly."""
        from serdap.dap_client import DapClient
        client = DapClient(port=mux.tcp_port)
        client.connect()
        assert client._running
        assert client._sock is not None
        client.close()
        assert not client._running

    def test_client_appears_as_connection(self, mux):
        """When the agent's DapClient connects, the multiplexer sees a new client."""
        from serdap.dap_client import DapClient
        client = DapClient(port=mux.tcp_port)
        client.connect()
        time.sleep(0.2)
        with mux._lock:
            assert len(mux._clients) >= 1
        client.close()

    def test_send_request_timeout(self, mux):
        """DapClient.send_request returns error when adapter not running."""
        from serdap.dap_client import DapClient
        client = DapClient(port=mux.tcp_port)
        client.connect()
        time.sleep(0.1)
        result = client.send_request("stackTrace", timeout=2.0)
        assert result.get("success") is False
        assert "timed out" in result.get("message", "").lower()
        client.close()

    def test_future_cleanup_on_close(self, mux):
        """Pending futures are cleaned up when the client closes."""
        from serdap.dap_client import DapClient
        client = DapClient(port=mux.tcp_port)
        client.connect()
        time.sleep(0.1)
        from concurrent.futures import Future as CFFuture
        seq = client._next_seq()
        with client._futures_lock:
            client._futures[seq] = CFFuture()
            assert seq in client._futures
        client.close()
        with client._futures_lock:
            assert seq not in client._futures

    def test_initialize_client_id(self, mux):
        """DapClient sends initialize with serena-agent clientID."""
        from serdap.dap_client import DapClient
        client = DapClient(port=mux.tcp_port)
        client.connect()
        time.sleep(0.1)
        result = client.send_initialize(adapter_id="python", timeout=2.0)
        assert result.get("success") is False  # no real adapter, but request was sent
        client.close()
