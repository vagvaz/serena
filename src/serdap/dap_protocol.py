import json
import logging
from typing import Any

from .dap_types import DAPMessage

ENCODING = "utf-8"
log = logging.getLogger(__name__)


def create_dap_message(body: bytes) -> tuple[bytes, bytes]:
    return (
        f"Content-Length: {len(body)}\r\n\r\n".encode(ENCODING),
        body,
    )


def parse_dap_message(data: bytes) -> dict[str, Any]:
    return json.loads(data)


def make_dap_request(command: str, seq: int, arguments: Any = None) -> dict[str, Any]:
    msg: dict[str, Any] = {
        "seq": seq,
        "type": "request",
        "command": command,
    }
    if arguments is not None:
        msg["arguments"] = arguments
    return msg


def make_dap_response(
    request_seq: int,
    command: str,
    seq: int,
    body: Any = None,
    success: bool = True,
    message: str | None = None,
) -> dict[str, Any]:
    msg: dict[str, Any] = {
        "seq": seq,
        "type": "response",
        "request_seq": request_seq,
        "command": command,
        "success": success,
    }
    if message is not None:
        msg["message"] = message
    if body is not None:
        msg["body"] = body
    return msg


def make_dap_error_response(
    request_seq: int,
    command: str,
    seq: int,
    message: str,
    error_body: Any = None,
) -> dict[str, Any]:
    return {
        "seq": seq,
        "type": "response",
        "request_seq": request_seq,
        "command": command,
        "success": False,
        "message": message,
        "body": {"error": error_body},
    }


def make_dap_event(event: str, seq: int, body: Any = None) -> dict[str, Any]:
    msg: dict[str, Any] = {
        "seq": seq,
        "type": "event",
        "event": event,
    }
    if body is not None:
        msg["body"] = body
    return msg


MUTATING_COMMANDS = frozenset({"continue", "next", "stepIn", "stepOut"})
ALWAYS_ALLOWED_COMMANDS = frozenset({"pause"})
READONLY_COMMANDS = frozenset({
    "stackTrace", "scopes", "variables", "evaluate",
    "setBreakpoints", "setFunctionBreakPoints",
    "threads", "source", "loadedSources",
    "setVariable", "setExpression",
    "gotoTargets", "stepInTargets", "completions",
    "exceptionInfo", "exceptionOptions",
    "dataBreakpoints", "dataBreakpointInfo",
    "breakpointLocations",
    "modules", "restartFrame",
})
CONTROL_NEVER = frozenset()


def content_length(line: bytes) -> int | None:
    if line.startswith(b"Content-Length: "):
        _, value = line.split(b"Content-Length: ")
        value = value.strip()
        try:
            return int(value)
        except ValueError:
            raise ValueError(f"Invalid Content-Length header: {value!r}")
    return None


def serialize_message(msg: DAPMessage) -> bytes:
    return json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode(ENCODING)


def message_bytes(msg: DAPMessage) -> bytes:
    body = serialize_message(msg)
    header = f"Content-Length: {len(body)}\r\n\r\n".encode(ENCODING)
    return header + body
