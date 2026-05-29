import json
from typing import Any, Dict


def encode(msg: Dict[str, Any]) -> bytes:
    return json.dumps(msg).encode("utf-8") + b"\n"


def decode(data: bytes) -> Dict[str, Any]:
    return json.loads(data.decode("utf-8"))


def request(cmd: str, **kwargs) -> bytes:
    return encode({"cmd": cmd, **kwargs})


def response(ok: bool = True, data: Any = None, error: str = None) -> bytes:
    payload = {"ok": ok}
    if data is not None:
        payload["data"] = data
    if error is not None:
        payload["error"] = error
    return encode(payload)
