"""Serve desktop HTTP requests over wsl.exe's binary stdin/stdout pipes."""
import io
import os
import shutil
import struct
import sys
from pathlib import Path

from branchdesk import Desk, Handler


class PipeRequest:
    """The socket operations used by a single BaseHTTPRequestHandler."""
    def __init__(self, request):
        self.input = io.BytesIO(request)
        self.output = io.BytesIO()

    def makefile(self, *args):
        return self.input

    def sendall(self, data):
        self.output.write(data)


def main():
    if sys.version_info < (3, 9) or not shutil.which("git"):
        raise RuntimeError("WSL requires Python 3.9+ and Git.")
    os.chdir(Path.home())
    source, dest = sys.stdin.buffer, sys.stdout.buffer
    port = int(source.readline(8))
    if not 0 < port <= 65535:
        raise ValueError("Invalid desktop port")
    pid = int(source.readline(16))
    lengths = [int(source.readline(8)), int(source.readline(8))]
    if pid < 0 or any(not 0 <= size < 32768 for size in lengths):
        raise ValueError("Invalid launcher metadata")
    paths = []
    for size in lengths:
        raw = source.read(size * 2)
        if len(raw) != size * 2: raise ValueError("Incomplete launcher metadata")
        paths.append(raw.decode('utf-16le'))
    with Desk(port, desktop=True, launcher=dict(pid=pid, path=paths[0], signal=paths[1])) as server:
        dest.write(f"BRANCHDESK/2 {port} {server.token}\n".encode("ascii"))
        dest.flush()
        while True:
            header = source.read(4)
            if not header:
                return
            size, = struct.unpack("<I", header)
            if size > 2_000_000 + 32768:
                raise ValueError("Request exceeds desktop transport limit")
            request = source.read(size)
            if len(request) != size:
                return
            channel = PipeRequest(request)
            Handler(channel, ("127.0.0.1", 0), server)
            reply = channel.output.getvalue()
            dest.write(struct.pack("<I", len(reply)))
            dest.write(reply)
            dest.flush()
