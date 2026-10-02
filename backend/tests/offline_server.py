"""Start the real Q API with the network blocked, for the offline replay test.

Only loopback is reachable, and never Ollama's port. Every blocked attempt is appended to the file named by $Q_NET_LOG,
so a test can prove the server tried nothing. Usage: python offline_server.py <port>
"""
import ipaddress
import os
import socket
import sys
from pathlib import Path

LOG = os.environ.get("Q_NET_LOG", "")
LOOPBACK = {"127.0.0.1", "::1", "localhost"}
OLLAMA_PORT = 11434


def _is_ip(host) -> bool:
    try:
        ipaddress.ip_address(str(host))
        return True
    except ValueError:
        return False


def _verdict(addr):
    """Why this destination is refused, or '' if it is allowed."""
    if not isinstance(addr, tuple):  # AF_UNIX
        return ""
    host, port = str(addr[0]), addr[1]
    if host not in LOOPBACK:
        return f"remote host {host}:{port}"
    if port == OLLAMA_PORT:
        return f"Ollama port {host}:{port}"
    return ""


def _refuse(why):
    if LOG:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(why + "\n")
    raise OSError(f"network blocked ({why})")


def install():
    real_connect, real_connect_ex, real_getaddrinfo = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo

    def connect(self, addr):
        why = _verdict(addr)
        if why:
            _refuse(why)
        return real_connect(self, addr)

    def connect_ex(self, addr):
        why = _verdict(addr)
        if why:
            _refuse(why)
        return real_connect_ex(self, addr)

    def getaddrinfo(host, *a, **k):
        if host not in (None, "", *LOOPBACK) and not _is_ip(host):  # IP literals are judged by connect() below
            _refuse(f"DNS lookup of {host}")
        return real_getaddrinfo(host, *a, **k)

    socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = connect, connect_ex, getaddrinfo


if __name__ == "__main__":
    install()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import uvicorn

    uvicorn.run("app.main:create_app", factory=True, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
