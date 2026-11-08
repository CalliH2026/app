from PyInstaller.utils.hooks import collect_data_files
# Preserve Chromium's signed .app/framework structure via ditto after packaging.
datas = collect_data_files('playwright', excludes=['driver/package/.local-browsers/**'])
