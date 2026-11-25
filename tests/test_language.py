"""Language persistence and translation-data integrity."""
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from language import LanguageStore

ROOT = Path(__file__).resolve().parents[1]


class LanguageTests(unittest.TestCase):
    def test_selection_persists_and_invalid_values_do_not_replace_it(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, XDG_STATE_HOME=directory):
            self.assertEqual(LanguageStore().read(), 'ko')
            for code in ('en', 'ja', 'ko'):
                LanguageStore().save(code)
                self.assertEqual(LanguageStore().read(), code)
            LanguageStore().save('ja')
            for value in ('zh', '', None, '../en'):
                with self.assertRaises(ValueError): LanguageStore().save(value)
            self.assertEqual(LanguageStore().read(), 'ja')
            LanguageStore().file.write_text('broken')
            self.assertEqual(LanguageStore().read(), 'ko')

    def test_native_shared_store_survives_host_state_directory_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            shared = Path(directory)/'Windows/Branchdesk'
            with patch.dict(os.environ, XDG_STATE_HOME=str(Path(directory)/'wsl-state')):
                LanguageStore(shared).save('en')
            with patch.dict(os.environ, XDG_STATE_HOME=str(Path(directory)/'different-state')):
                self.assertEqual(LanguageStore(shared).read(), 'en')
                self.assertEqual((shared/'language.txt').read_bytes(), b'en')

    def test_catalogs_are_complete_and_preserve_format_placeholders(self):
        catalog = json.loads((ROOT/'web/i18n.json').read_text())
        self.assertEqual(set(catalog['en']), set(catalog['ja']))
        self.assertGreater(len(catalog['en']), 500)
        for lang in ('en', 'ja'):
            for source, translated in catalog[lang].items():
                self.assertIsInstance(translated, str)
                self.assertTrue(translated)
                self.assertFalse(re.search('[가-힣]', translated), (lang, source))
                self.assertEqual(set(re.findall(r'\{\w+\}', source)), set(re.findall(r'\{\w+\}', translated)), (lang, source))


if __name__ == '__main__': unittest.main()
