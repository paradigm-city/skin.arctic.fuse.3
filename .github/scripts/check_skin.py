#!/usr/bin/env python3
"""Static checks for the skin, run by CI and usable locally.

Checks:
  - every tracked XML file is well-formed
  - every tracked JSON file parses
  - every language strings.po parses (needs polib: pip install polib)
  - addon.xml has the fields Kodi needs, and its icon and fanart exist
  - every $VAR[...], $EXP[...] and <include> used in 1080i/ is defined in 1080i/

Problems listed in known-issues.txt (next to this script) are reported as
warnings only. Any other problem fails the run.

Usage: python .github/scripts/check_skin.py
"""
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = Path(__file__).with_name('known-issues.txt')
IN_CI = os.environ.get('GITHUB_ACTIONS') == 'true'

# Includes defined in files that script.skinvariables generates at runtime (git-ignored).
GENERATED_INCLUDE_PREFIXES = ('skinvariables-', 'script-skinvariables', 'skinshortcuts')

findings = []  # (key, file, line, message)


def add(key, file, message, line=None):
    findings.append((key, file, line, message))


def tracked(*patterns):
    out = subprocess.run(['git', 'ls-files', '--', *patterns], cwd=ROOT,
                         capture_output=True, text=True, encoding='utf-8', check=True).stdout
    return [f for f in out.splitlines() if f]


def check_xml():
    trees = {}
    for f in tracked('*.xml'):
        try:
            trees[f] = ET.parse(ROOT / f).getroot()
        except ET.ParseError as e:
            add(f'xml:{f}', f, f'XML is not well-formed: {e}', e.position[0])
    return trees


def check_json():
    for f in tracked('*.json'):
        try:
            with open(ROOT / f, encoding='utf-8') as fh:
                json.load(fh)
        except ValueError as e:
            add(f'json:{f}', f, f'JSON does not parse: {e}', getattr(e, 'lineno', None))


def check_po():
    try:
        import polib
    except ImportError:
        print('polib is not installed, skipping .po checks (pip install polib)')
        return
    for f in tracked('language/*/strings.po'):
        try:
            polib.pofile(str(ROOT / f))
        except Exception as e:  # polib raises plain IOError/OSError with the line number in the text
            m = re.search(r'line (\d+)', str(e))
            add(f'po:{f}', f, f'PO file does not parse: {e}', int(m.group(1)) if m else None)


def check_addon(trees):
    f = 'addon.xml'
    root = trees.get(f)
    if root is None:
        return  # already reported as an XML error
    for attr in ('id', 'name', 'version', 'provider-name'):
        if not root.get(attr):
            add(f'addon:missing-{attr}', f, f'addon.xml is missing the {attr} attribute')
    version = root.get('version') or ''
    if version and not re.fullmatch(r'\d+\.\d+\.\d+([~+.-][0-9A-Za-z.]+)?', version):
        add('addon:version-format', f, f'Version "{version}" is not in x.y.z form')
    imports = {i.get('addon') for i in root.iter('import')}
    if 'xbmc.gui' not in imports:
        add('addon:no-xbmc.gui', f, 'addon.xml does not import xbmc.gui')
    meta = next((e for e in root.iter('extension') if e.get('point') == 'xbmc.addon.metadata'), None)
    if meta is None:
        add('addon:no-metadata', f, 'addon.xml has no xbmc.addon.metadata extension')
        return
    for tag in ('summary', 'description', 'license', 'platform'):
        if meta.find(tag) is None:
            add(f'addon:missing-{tag}', f, f'addon.xml metadata has no <{tag}>')
    assets = meta.find('assets')
    for tag in ('icon', 'fanart'):
        el = assets.find(tag) if assets is not None else None
        if el is not None and el.text and not (ROOT / el.text.strip()).exists():
            add(f'addon:asset-{tag}', f, f'Asset {el.text.strip()} listed in addon.xml does not exist')


REF = re.compile(r'\$(VAR|EXP)\[([^\],\[]+)')


def check_references(trees):
    skin = {f: r for f, r in trees.items() if f.startswith('1080i/')}
    defined = {'VAR': set(), 'EXP': set(), 'include': set()}
    kinds = {'variable': 'VAR', 'expression': 'EXP', 'include': 'include'}
    for root in skin.values():
        for el in root.iter():
            if el.tag in kinds and el.get('name'):
                defined[kinds[el.tag]].add(el.get('name'))

    seen = set()

    def ref(kind, name, f):
        name = name.strip()
        if not name or '$' in name or '{' in name:
            return  # built from $PARAM or a template at runtime
        if kind == 'include' and name.startswith(GENERATED_INCLUDE_PREFIXES):
            return
        if name in defined[kind] or (kind, name, f) in seen:
            return
        seen.add((kind, name, f))
        label = {'VAR': 'variable', 'EXP': 'expression', 'include': 'include'}[kind]
        add(f'ref:{kind}:{name}', f, f'Undefined {label} "{name}"')

    for f, root in skin.items():
        for el in root.iter():
            for value in [el.text or '', *el.attrib.values()]:
                for kind, name in REF.findall(value):
                    ref(kind, name, f)
            if el.tag == 'include' and el.get('name') is None:
                ref('include', el.get('content') or el.text or '', f)


def load_baseline():
    if not BASELINE.exists():
        return set()
    lines = BASELINE.read_text(encoding='utf-8').splitlines()
    return {l.split('#', 1)[0].strip() for l in lines if l.split('#', 1)[0].strip()}


def report(level, file, line, message):
    if IN_CI:
        loc = f' file={file}' + (f',line={line}' if line else '') if file else ''
        print(f'::{level}{loc}::{message}')
    else:
        where = f'{file}:{line}' if line else (file or '')
        print(f'{level.upper():8} {where}  {message}')


def main():
    trees = check_xml()
    check_json()
    check_po()
    check_addon(trees)
    check_references(trees)

    baseline = load_baseline()
    new = [f for f in findings if f[0] not in baseline]
    known = [f for f in findings if f[0] in baseline]
    stale = sorted(baseline - {f[0] for f in findings})

    for key, file, line, message in known:
        report('warning', file, line, f'{message} (known issue: {key})')
    for key in stale:
        report('notice', None, None, f'Known issue "{key}" no longer occurs. Remove it from known-issues.txt.')
    for key, file, line, message in new:
        report('error', file, line, f'{message} [{key}]')

    print(f'\n{len(new)} new problem(s), {len(known)} known issue(s), {len(stale)} stale baseline entr(y/ies).')
    return 1 if new else 0


if __name__ == '__main__':
    sys.exit(main())
