"""Persist an app-wide language independently of disposable browser profiles."""
import os
from pathlib import Path
import tempfile
import shutil
from environments import state_root

LANGUAGES = ('ko', 'en', 'ja')


class LanguageStore:
    def __init__(self, shared=None):
        self.file = (Path(shared) if shared else state_root()) / 'language.txt'

    def read(self):
        try: value = self.file.read_text(encoding='ascii').strip()
        except (OSError, UnicodeError): value = 'ko'
        return value if value in LANGUAGES else 'ko'

    def save(self, value):
        if value not in LANGUAGES: raise ValueError('지원하지 않는 언어입니다.')
        self.file.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=self.file.parent)
        try:
            with os.fdopen(fd, 'w', encoding='ascii') as file:
                file.write(value); file.flush(); os.fsync(file.fileno())
            os.replace(name, self.file)
        finally: Path(name).unlink(missing_ok=True)
        return value


def copy_windows_translations(destination):
    root = Path(__file__).resolve().parent
    shutil.copyfile(root/'windows/i18n.ps1', Path(destination)/'i18n.ps1')
    shutil.copyfile(root/'web/i18n.json', Path(destination)/'i18n.json')
