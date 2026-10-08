#!/usr/bin/env python3
"""Build an installable Kodi zip from the committed tree (HEAD).

The zip is named <id>-<version>.zip and contains a single top-level <id>/ folder,
which is what Kodi's "Install from zip file" expects. The id, name and version
are read from addon.xml. Repository-only files (.github, .gitignore, .gitattributes)
are left out.

Usage: python .github/scripts/build_zip.py [output-dir]   (default: dist)

In GitHub Actions it also writes id, name, version, tag, zip and zip_name to
$GITHUB_OUTPUT. The release tag is <id>-<version>, so it never collides with
upstream's v* tags.
"""
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXCLUDE = ('.github', '.gitignore', '.gitattributes')


def main():
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else 'dist')
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    # Read addon.xml from HEAD so the zip and its name always agree.
    addon_xml = subprocess.run(['git', 'show', 'HEAD:addon.xml'], cwd=ROOT,
                               capture_output=True, check=True).stdout
    addon = ET.fromstring(addon_xml)
    addon_id, version, name = addon.get('id'), addon.get('version'), addon.get('name')

    zip_name = f'{addon_id}-{version}.zip'
    zip_path = out_dir / zip_name
    pathspec = ['.'] + [f':(exclude){p}' for p in EXCLUDE]
    subprocess.run(['git', 'archive', '--format=zip', f'--prefix={addon_id}/',
                    '-o', str(zip_path), 'HEAD', '--', *pathspec], cwd=ROOT, check=True)
    print(f'Built {zip_path} ({zip_path.stat().st_size // 1024} KiB)')

    outputs = {'id': addon_id, 'name': name, 'version': version,
               'tag': f'{addon_id}-{version}', 'zip': str(zip_path), 'zip_name': zip_name}
    gh_out = os.environ.get('GITHUB_OUTPUT')
    if gh_out:
        with open(gh_out, 'a', encoding='utf-8') as fh:
            fh.writelines(f'{k}={v}\n' for k, v in outputs.items())


if __name__ == '__main__':
    main()
