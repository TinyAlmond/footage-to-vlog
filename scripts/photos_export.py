"""macOS Photos library: list the videos (or photos) of a date range, then export the originals to a folder.

Listing reads every item's name, date and size in a few bulk Apple events (JXA), so it is quick even for large
libraries. Exporting uses Photos' own AppleScript export "with using originals"; items kept only in iCloud are
downloaded first, which can take a while. The first run asks for permission to control Photos (Automation).

usage: python photos_export.py list --since 2025-05-10 [--until 2025-05-14] [--kind video|photo|all]
                                    [--orient landscape|portrait] [--min-dur 0] [--json list.json]
       python photos_export.py export --json list.json --to DIR [--ids ID,ID]
"""
import argparse
import json
import os
import subprocess
import tempfile

LIST_JS = r'''
function run(argv) {
  const since = new Date(argv[0]), until = new Date(argv[1]);
  const Photos = Application('Photos');
  const items = Photos.mediaItems;
  const names = items.filename(), dates = items.date(), ids = items.id(), w = items.width(), h = items.height();
  const out = [];
  for (let i = 0; i < names.length; i++) {
    const d = dates[i];
    if (!d || d < since || d >= until) continue;
    out.push({ id: ids[i], name: names[i] || '', date: d.toISOString(), w: w[i], h: h[i] });
  }
  return JSON.stringify(out);
}
'''
VIDEO = ('.mov', '.mp4', '.m4v')


def osascript(lang, script, *args, timeout=7200):
    with tempfile.NamedTemporaryFile('w', suffix='.js' if lang == 'JavaScript' else '.applescript',
                                     delete=False) as f:
        f.write(script)
    try:
        r = subprocess.run(['osascript', '-l', lang, f.name, *args], capture_output=True, text=True, timeout=timeout)
    finally:
        os.remove(f.name)
    if r.returncode:
        raise SystemExit(f'osascript failed: {r.stderr.strip()}  (allow Terminal/Claude to control Photos in '
                         f'System Settings > Privacy & Security > Automation)')
    return r.stdout.strip()


def cmd_list(a):
    until = a.until or '2100-01-01'
    items = json.loads(osascript('JavaScript', LIST_JS, a.since, until))
    out = []
    for it in items:
        video = it['name'].lower().endswith(VIDEO)
        if (a.kind == 'video' and not video) or (a.kind == 'photo' and video):
            continue
        if a.orient == 'landscape' and not it['w'] >= it['h']:
            continue
        if a.orient == 'portrait' and not it['h'] > it['w']:
            continue
        out.append(it)
    out.sort(key=lambda r: r['date'])
    for r in out:
        print(f"{r['date'][:19].replace('T', ' ')}Z  {r['w']:>5d}x{r['h']:<5d} {r['name']}")
    print(f'{len(out)} items (portrait/landscape from stored size; phone videos report their display size)')
    if a.json:
        json.dump(out, open(a.json, 'w'), indent=1)
        print('wrote', a.json)


def cmd_export(a):
    items = json.load(open(a.json))
    if a.ids:
        keep = set(a.ids.split(','))
        items = [r for r in items if r['id'] in keep]
    os.makedirs(a.to, exist_ok=True)
    dest = os.path.abspath(a.to)
    for i in range(0, len(items), 20):                   # batches: one huge export can time out
        batch = items[i:i + 20]
        refs = ', '.join(f'media item id "{r["id"]}"' for r in batch)
        script = (f'with timeout of 7200 seconds\n tell application "Photos"\n'
                  f'  export {{{refs}}} to (POSIX file "{dest}") with using originals\n end tell\nend timeout\n')
        osascript('AppleScript', script)
        print(f'exported {i + len(batch)}/{len(items)}', flush=True)
    names = {r['name'] for r in items}
    got = [n for n in os.listdir(dest) if n in names]
    note = '' if len(got) == len(names) else '  (some may have been renamed or are still in iCloud)'
    print(f'{len(got)}/{len(names)} files present in {dest}{note}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    l_ = sub.add_parser('list')
    l_.add_argument('--since', required=True, help='YYYY-MM-DD (local midnight)')
    l_.add_argument('--until', help='YYYY-MM-DD, exclusive')
    l_.add_argument('--kind', default='video', choices=['video', 'photo', 'all'])
    l_.add_argument('--orient', choices=['landscape', 'portrait'])
    l_.add_argument('--json')
    e = sub.add_parser('export')
    e.add_argument('--json', required=True)
    e.add_argument('--to', required=True)
    e.add_argument('--ids')
    a = ap.parse_args()
    if a.cmd == 'list':
        a.since = a.since + 'T00:00:00'
        a.until = (a.until + 'T00:00:00') if a.until else None
        cmd_list(a)
    else:
        cmd_export(a)


if __name__ == '__main__':
    main()
