import http.client
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlsplit

from desktop_pipe import desktop

ROOT = Path(__file__).resolve().parents[1]


class DesktopTests(unittest.TestCase):
    def test_packaged_pipe_while_listening_port_already_owned(self):
        exe = Path(os.environ.get("BRANCHDESK_EXE", ROOT / "dist/Branchdesk.exe")).resolve()
        if not exe.exists():
            exe = ROOT / "Branchdesk.exe"
        with tempfile.TemporaryDirectory() as temp, desktop(exe, temp) as url:
            address = urlsplit(url)
            def request(path, data=None, **headers):
                conn = http.client.HTTPConnection(address.hostname, address.port, timeout=10)
                try:
                    conn.request("GET" if data is None else "POST", path, data, headers=headers)
                    response = conn.getresponse()
                    return response.status, response.read()
                finally:
                    conn.close()
            self.assertEqual(request("/_ready"), (200, b"branchdesk-ready"))
            self.assertEqual(request("/_ready", Host="example.invalid")[0], 404)
            self.assertEqual(request("/api/repos", "{}")[0], 403)
            key = {"X-Desk-Key": address.fragment}
            self.assertEqual(request("/api/repos", "{}", Origin="https://example.invalid", **key)[0], 403)
            body = json.dumps({"path": temp + "/"})
            self.assertEqual(request("/api/directories", body)[0], 403)
            (Path(temp) / "한글 파일").touch()
            folder = Path(temp) / "한글 폴더"
            folder.mkdir()
            (Path(temp) / ".숨김").mkdir()
            (folder / "child").mkdir()
            for prefix, expected in [
                (temp + "/", [str(folder) + "/"]),
                (temp + "/한", [str(folder) + "/"]),
                (str(folder) + "/", [str(folder / "child") + "/"]),
                (temp + "/.", [temp + "/.숨김/"]),
                (temp + "/없음/", []),
                ("~", ["~/"]),
            ]:
                status, body = request("/api/directories", json.dumps({"path": prefix}), **key)
                self.assertEqual((status, json.loads(body)["value"]), (200, expected))
            path = str(Path(temp) / "한글 저장소")
            status, body = request("/api/new", json.dumps(dict(mode="init", path=path)), **key)
            self.assertEqual((status, json.loads(body)["value"]), (200, path))
            self.assertEqual(json.loads(request("/api/repos", "{}", **key)[1])["value"], [path])
            with ThreadPoolExecutor(max_workers=6) as pool:
                sizes = list(pool.map(lambda name: len(request(name)[1]), ["/", "/app.js", "/commands.js", "/style.css"] * 2))
            self.assertEqual(sizes[:4], sizes[4:])
            self.assertTrue(all(n > 1000 for n in sizes))
