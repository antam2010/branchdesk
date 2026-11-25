"""Build the Windows executable with MSVC (x64 developer prompt) or MinGW-w64."""
import io
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ["branchdesk.py", "tab_store.py", "gitdesk.py", "web/app.js", "web/index.html",
         "web/style.css", "workspace_ops.py", "partial.py", "web/commands.js", "windows/session.py"]


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


def main():
    dest = (ROOT / "dist" / "Branchdesk.exe").resolve()
    dest.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        build = Path(temp)
        header(build)
        source = str(ROOT / "windows" / "launcher.c")
        if os.name == "nt" and shutil.which("cl"):
            command = ["cl", "/nologo", "/O2", "/utf-8", "/W4", "/I"+temp, source,
                       "/Fe:"+str(dest), "/link", "/SUBSYSTEM:WINDOWS", "user32.lib", "shell32.lib", "ws2_32.lib"]
        else:
            cc = os.environ.get("CC", "x86_64-w64-mingw32-gcc")
            command = [cc, "-O2", "-Wall", "-Wextra", "-municode", "-mwindows",
                       "-I", temp, source, "-o", str(dest), "-lshell32", "-lws2_32"]
        subprocess.run(command, cwd=build, check=True)
    print(dest)


if __name__ == "__main__":
    main()
