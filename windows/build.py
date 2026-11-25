"""Build the Windows executable with MSVC (x64 developer prompt) or MinGW-w64."""
import io
import base64
import json
import re
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ["branchdesk.py", "tab_store.py", "gitdesk.py", "web/app.js", "web/panes.js", "web/index.html",
         "web/style.css", "web/icon.png", "web/favicon.ico", "workspace_ops.py", "commit_ops.py", "partial.py", "web/commands.js", "web/context.js", "web/update.js", "updater.py", "windows/update.ps1", "windows/session.py", "environments.py", "process_utils.py", "web/environments.js", "windows/tools.ps1", "desktop_actions.py", "windows/desktop.ps1", "language.py", "web/i18n.js", "web/i18n.json", "windows/i18n.ps1"]


def payload():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name in FILES:
            entry = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, (ROOT / name).read_bytes())
    return buf.getvalue()


def header(directory):
    blob = payload()
    lines = [", ".join(str(b) for b in blob[n:n+20]) for n in range(0, len(blob), 20)]
    (directory / "payload.h").write_text(
        '#define PAYLOAD_SIZE L"' + str(len(blob)) + '"\n'
        + "static const unsigned char payload[] = {\n" + ",\n".join(lines) + "\n};\n",
        encoding="ascii")
    source = (ROOT / "windows/setup.ps1").read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    embedded = base64.b64encode((ROOT / "windows/tools.ps1").read_bytes()).decode('ascii')
    source = source.replace('# EMBED_TOOLS', "$ToolsScript = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + embedded + "'))")
    catalog_text = (ROOT / 'web/i18n.json').read_text(encoding='utf-8')
    loader = (ROOT / 'windows/i18n.ps1').read_text(encoding='utf-8')
    full_catalog = json.loads(catalog_text)
    native_keys = set()
    for script_name in ('setup.ps1', 'tools.ps1'):
        for match in re.finditer(r"T '((?:''|[^'])*)'", (ROOT/'windows'/script_name).read_text(encoding='utf-8')):
            native_keys.add(match[1].replace("''", "'").strip())
    native_catalog = json.dumps({lang: {key: value for key, value in entries.items() if key in native_keys} for lang, entries in full_catalog.items()}, ensure_ascii=False, separators=(',', ':'))
    bootstrap = "$BranchdeskCatalogJson = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + base64.b64encode(native_catalog.encode()).decode() + "'))\n" + loader + "\n"
    embedded_bootstrap = base64.b64encode(bootstrap.encode()).decode()
    source = source.replace('# EMBED_I18N', "$I18nBootstrap = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + embedded_bootstrap + "'))\n" + bootstrap, 1)
    setup = b"\xef\xbb\xbf" + source.encode('utf-8')
    catalog = json.loads(catalog_text)
    messages = [json.loads('"'+raw+'"') for raw in re.findall(r'L"((?:\\.|[^"\\])*)"', (ROOT/'windows/launcher.c').read_text()) if re.search('[가-힣]', raw)]
    quote = lambda value: 'L' + json.dumps(value, ensure_ascii=False)
    entries = ["{" + ','.join(quote(value) for value in (key, catalog['en'].get(key,key), catalog['ja'].get(key,key))) + "}" for key in dict.fromkeys(messages)]
    (directory/'i18n.h').write_text('static const WCHAR *const native_messages[][3] = {\n'+',\n'.join(entries)+'\n};\n', encoding='utf-8')
    lines = [", ".join(str(b) for b in setup[n:n+20]) for n in range(0, len(setup), 20)]
    (directory / "setup.h").write_text(
        "static const unsigned char setup_script[] = {\n" + ",\n".join(lines) + "\n};\n", encoding="ascii")


def main():
    dest = (ROOT / "dist" / "Branchdesk.exe").resolve()
    dest.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        build = Path(temp)
        header(build)
        shutil.copyfile(ROOT / "windows/branchdesk.rc", build / "branchdesk.rc")
        shutil.copyfile(ROOT / "web/favicon.ico", build / "branchdesk.ico")
        source = str(ROOT / "windows" / "launcher.c")
        if os.name == "nt" and shutil.which("cl"):
            subprocess.run(["rc", "/nologo", "/fo", "branchdesk.res", "branchdesk.rc"], cwd=build, check=True)
            command = ["cl", "/nologo", "/O2", "/utf-8", "/W4", "/I"+temp, source,
                       "branchdesk.res", "/Fe:"+str(dest), "/link", "/SUBSYSTEM:WINDOWS", "user32.lib", "shell32.lib", "ws2_32.lib"]
        else:
            cc = shlex.split(os.environ.get("CC", "x86_64-w64-mingw32-gcc"))
            windres = shlex.split(os.environ.get("WINDRES", "x86_64-w64-mingw32-windres"))
            subprocess.run(windres + ["branchdesk.rc", "-O", "coff", "-o", "branchdesk.o"], cwd=build, check=True)
            command = cc + ["-O2", "-Wall", "-Wextra", "-municode", "-mwindows",
                       "-I", temp, source, "branchdesk.o", "-o", str(dest), "-lshell32", "-lws2_32"]
        subprocess.run(command, cwd=build, check=True)
    print(dest)


if __name__ == "__main__":
    main()
