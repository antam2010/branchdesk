"""Run the desktop payload with a local test HTTP listener in place of WinSock."""
import io
import os
import socketserver
import struct
import subprocess
import sys
import threading
import zipfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def bundled_command(executable):
    exe = Path(executable).read_bytes()
    start = exe.index(b"PK\x03\x04")
    end = exe.index(b"PK\x05\x06", start) + 22
    blob = exe[start:end]
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        assert archive.testzip() is None
        for name in archive.namelist():
            assert archive.read(name) == (ROOT / name).read_bytes(), name
    prefix = ' --exec python3 -I -u -c "'
    pos = exe.index(prefix.encode("utf-16le"))
    end = pos
    while exe[end:end+2] != b"\0\0":
        end += 2
    return exe[pos:end].decode("utf-16le")[len(prefix):-1], blob


class TestBridge(socketserver.StreamRequestHandler):
    def handle(self):
        headers = []
        length = 0
        while True:
            line = self.rfile.readline(32768)
            if not line:
                return
            headers.append(line)
            if line == b"\r\n":
                break
            if line.lower().startswith(b"content-length:"):
                length = int(line.split(b":", 1)[1])
        request = b"".join(headers) + self.rfile.read(length)
        child = self.server.child
        with self.server.pipe_lock:
            child.stdin.write(struct.pack("<I", len(request)) + request)
            child.stdin.flush()
            size, = struct.unpack("<I", child.stdout.read(4))
            response = child.stdout.read(size)
        self.wfile.write(response)


@contextmanager
def desktop(executable, workdir):
    command, blob = bundled_command(executable)
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), TestBridge) as server:
        server.daemon_threads = True
        port = server.server_address[1]
        with subprocess.Popen([sys.executable, "-I", "-u", "-c", command], cwd=workdir, env=dict(os.environ, XDG_STATE_HOME=str(Path(workdir) / ".test-state")),
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE) as child:
            server.child = child
            server.pipe_lock = threading.Lock()
            try:
                child.stdin.write(blob + f"{port}\n".encode("ascii"))
                child.stdin.flush()
                marker, echoed_port, key = child.stdout.readline().decode().split()
                assert marker == "BRANCHDESK/2" and int(echoed_port) == port
                worker = threading.Thread(target=server.serve_forever)
                worker.start()
                try:
                    yield f"http://127.0.0.1:{port}/#{key}"
                finally:
                    server.shutdown()
                    worker.join()
            finally:
                child.stdin.close()
                assert child.wait(timeout=10) == 0
