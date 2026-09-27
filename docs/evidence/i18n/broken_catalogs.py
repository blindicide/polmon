"""Run the completeness gate against deliberately broken copies of the catalogs."""
import runpy
import sys

sys.path.insert(0, "src")
from polmon.client import locales  # noqa: E402

ru = dict(locales.CATALOGS["ru"])
del ru["common.close"]  # 1. a key missing from Russian
ru["log.done"] = "Готово"  # 2. the {name} placeholder dropped
ru["common.cancel"] = "Cancel"  # 3. left untranslated
ru["count.frames_captured"] = {"one": "{count} кадр", "other": "{count} кадров"}  # 4. plural forms
en = dict(locales.CATALOGS["en"])
en["common.never_used"] = "Never shown"  # 5. a key no code uses
en["common.yes"] = "Да"  # 6. Cyrillic in English
locales.CATALOGS["ru"], locales.CATALOGS["en"] = ru, en
sys.argv = ["scripts/i18n-completeness.py"]
runpy.run_path("scripts/i18n-completeness.py", run_name="__main__")
