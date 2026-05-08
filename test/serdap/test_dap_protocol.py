import json
import pytest

from serdap.dap_protocol import (
    create_dap_message,
    parse_dap_message,
    make_dap_request,
    make_dap_response,
    make_dap_event,
    make_dap_error_response,
    content_length,
    serialize_message,
    message_bytes,
    MUTATING_COMMANDS,
    ALWAYS_ALLOWED_COMMANDS,
    READONLY_COMMANDS,
)


class TestDapProtocol:
    def test_content_length_valid(self):
        assert content_length(b"Content-Length: 42") == 42
        assert content_length(b"Content-Length: 0") == 0
        assert content_length(b"Content-Length: 1024") == 1024

    def test_content_length_invalid(self):
        assert content_length(b"Content-Type: application/json") is None
        assert content_length(b"Random header") is None

    def test_content_length_malformed(self):
        with pytest.raises(ValueError, match="Invalid Content-Length"):
            content_length(b"Content-Length: abc")

    def test_create_dap_message(self):
        body = b'{"seq":1,"type":"request","command":"stackTrace"}'
        header, body_out = create_dap_message(body)
        assert header == f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
        assert body_out == body

    def test_parse_dap_message(self):
        data = b'{"seq":1,"type":"request","command":"stackTrace"}'
        msg = parse_dap_message(data)
        assert msg["seq"] == 1
        assert msg["type"] == "request"
        assert msg["command"] == "stackTrace"

    def test_make_dap_request(self):
        req = make_dap_request("stackTrace", 1, {"threadId": 1})
        assert req["seq"] == 1
        assert req["type"] == "request"
        assert req["command"] == "stackTrace"
        assert req["arguments"] == {"threadId": 1}

    def test_make_dap_request_no_args(self):
        req = make_dap_request("disconnect", 2)
        assert req["seq"] == 2
        assert req["command"] == "disconnect"
        assert "arguments" not in req

    def test_make_dap_response_success(self):
        resp = make_dap_response(1, "stackTrace", 2, body={"stackFrames": []})
        assert resp["request_seq"] == 1
        assert resp["command"] == "stackTrace"
        assert resp["seq"] == 2
        assert resp["success"] is True
        assert resp["body"] == {"stackFrames": []}

    def test_make_dap_response_no_body(self):
        resp = make_dap_response(1, "continue", 2)
        assert resp["success"] is True
        assert "body" not in resp

    def test_make_dap_error_response(self):
        resp = make_dap_error_response(1, "stackTrace", 2, "Something went wrong")
        assert resp["request_seq"] == 1
        assert resp["success"] is False
        assert resp["message"] == "Something went wrong"
        assert resp["body"]["error"] is None

    def test_make_dap_error_response_with_error_body(self):
        resp = make_dap_error_response(1, "evaluate", 2, "error", error_body={"id": 1, "format": "err"})
        assert resp["body"]["error"] == {"id": 1, "format": "err"}

    def test_make_dap_event(self):
        event = make_dap_event("stopped", 1, body={"reason": "breakpoint", "threadId": 1})
        assert event["type"] == "event"
        assert event["event"] == "stopped"
        assert event["seq"] == 1
        assert event["body"] == {"reason": "breakpoint", "threadId": 1}

    def test_make_dap_event_no_body(self):
        event = make_dap_event("terminated", 2)
        assert event["type"] == "event"
        assert "body" not in event

    def test_serialize_deserialize_roundtrip(self):
        req = make_dap_request("stackTrace", 1, {"threadId": 1})
        data = serialize_message(req)
        parsed = json.loads(data)
        assert parsed == req

    def test_message_bytes_format(self):
        msg = {"seq": 1, "type": "request", "command": "stackTrace"}
        raw = message_bytes(msg)
        assert raw.startswith(b"Content-Length: ")
        separator = b"\r\n\r\n"
        assert separator in raw
        header_end = raw.find(separator) + len(separator)
        body = raw[header_end:]
        assert json.loads(body) == msg

    def test_control_command_classification(self):
        assert "next" in MUTATING_COMMANDS
        assert "stepIn" in MUTATING_COMMANDS
        assert "stepOut" in MUTATING_COMMANDS
        assert "continue" in MUTATING_COMMANDS
        assert "pause" in ALWAYS_ALLOWED_COMMANDS
        assert "setBreakpoints" in READONLY_COMMANDS
        assert "stackTrace" in READONLY_COMMANDS
        assert "variables" in READONLY_COMMANDS
        assert "evaluate" in READONLY_COMMANDS
        assert "scopes" in READONLY_COMMANDS
        assert "threads" in READONLY_COMMANDS
        assert "source" in READONLY_COMMANDS
        assert "disconnect" not in MUTATING_COMMANDS
        assert "disconnect" not in ALWAYS_ALLOWED_COMMANDS
        assert "disconnect" not in READONLY_COMMANDS

    def test_no_overlap_between_command_sets(self):
        assert MUTATING_COMMANDS.isdisjoint(ALWAYS_ALLOWED_COMMANDS)
        assert MUTATING_COMMANDS.isdisjoint(READONLY_COMMANDS)
        assert ALWAYS_ALLOWED_COMMANDS.isdisjoint(READONLY_COMMANDS)
