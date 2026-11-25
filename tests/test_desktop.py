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
    def test_launcher_metadata_handles_spaces_and_utf16_surrogates(self):
        info = dict(pid=42, path='C:\\Users\\이 대호😀\\Branchdesk.exe', signal='C:\\Temp\\시작\\update.signal')
        with tempfile.TemporaryDirectory() as temp, desktop(ROOT / 'Branchdesk.exe', temp, info) as url:
            address = urlsplit(url)
            connection = http.client.HTTPConnection(address.hostname, address.port, timeout=10)
            try:
                connection.request('POST', '/api/app-update', json.dumps(dict(action='status')), {'X-Desk-Key': address.fragment})
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertTrue(json.loads(response.read())['value']['supported'])
            finally:
                connection.close()

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
            for url, name in [("/icon.png", "icon.png"), ("/favicon.ico", "favicon.ico")]:
                status, body = request(url)
                self.assertEqual(status, 200)
                self.assertEqual(body, (ROOT / "web" / name).read_bytes())

    def test_language_preference_survives_desktop_restarts(self):
        def language(url, **data):
            address = urlsplit(url)
            connection = http.client.HTTPConnection(address.hostname,address.port,timeout=10)
            try:
                connection.request('POST','/api/language',json.dumps(data),{'X-Desk-Key':address.fragment})
                response=connection.getresponse()
                self.assertEqual(response.status,200)
                return json.loads(response.read())['value']['language']
            finally: connection.close()
        with tempfile.TemporaryDirectory() as directory:
            with desktop(ROOT/'Branchdesk.exe',directory) as first:
                self.assertEqual(language(first),'ko')
                self.assertEqual(language(first,action='save',language='ja'),'ja')
            with desktop(ROOT/'Branchdesk.exe',directory) as second:
                self.assertEqual(language(second),'ja')

    def test_tabs_survive_desktop_restarts(self):
        exe = ROOT / "Branchdesk.exe"
        def api(url, endpoint, **data):
            address = urlsplit(url)
            conn = http.client.HTTPConnection(address.hostname, address.port, timeout=10)
            try:
                conn.request("POST", "/api/" + endpoint, json.dumps(data), {"X-Desk-Key": address.fragment})
                response = conn.getresponse()
                body = json.loads(response.read())
                self.assertEqual(response.status, 200, body)
                self.assertNotIn("warning", body)
                return body["value"]
            finally:
                conn.close()

        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            a, b, c = (str(parent / name) for name in ["프로젝트 A", "B", "C"])
            with desktop(exe, parent) as first:
                for path in [a, b, c]:
                    api(first, "new", mode="init", path=path)
                api(first, "select-tab", repo=b)
            with desktop(exe, parent) as second:
                self.assertNotEqual(urlsplit(first).fragment, urlsplit(second).fragment)
                self.assertEqual(api(second, "workspace"), {"repos": [a, b, c], "active": b})
                self.assertEqual(api(second, "recent"), [b, c, a])
                with desktop(exe, parent) as other:
                    api(other, "close", repo=a)
                    api(second, "close", repo=b)
            with desktop(exe, parent) as third:
                self.assertEqual(api(third, "workspace"), {"repos": [c], "active": c})
                api(third, "open", path=a)
            Path(a).rename(parent / "moved")
            with desktop(exe, parent) as fourth:
                self.assertEqual(api(fourth, "workspace"), {"repos": [c], "active": c})
                api(fourth, "close", repo=c)
            with desktop(exe, parent) as empty:
                self.assertEqual(api(empty, "workspace"), {"repos": [], "active": None})
                self.assertEqual(api(empty, "recent"), [a, b, c])
                api(empty, "open", path=b, exact=True)
                api(empty, "open", path=b, exact=True)
                self.assertEqual(api(empty, "workspace"), {"repos": [b], "active": b})
                self.assertEqual(api(empty, "recent"), [b, a, c])

            state_file = parent / ".test-state/branchdesk/tabs.json"
            state_file.write_text(json.dumps({"repos": [b, c], "active": c}))
            with desktop(exe, parent) as migrated:
                self.assertEqual(api(migrated, "recent"), [c, b])
                api(migrated, "close", repo=b)
            with desktop(exe, parent) as reopened:
                self.assertEqual(api(reopened, "recent"), [c, b])
                self.assertEqual(api(reopened, "workspace")["repos"], [c])
