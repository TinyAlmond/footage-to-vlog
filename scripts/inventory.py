"""Inventory of a footage folder: one line per clip with what decides how it can be used.

Columns: created (UTC), length, size, frame rate, codec / bit depth, sound, and notes: HDR (convert before editing),
a DJI .LRF proxy that runs longer than the main file (check offsets), slow-motion headroom, portrait, no sound.
Sorted by creation time. --json writes everything (incl. GPS tags with --gps) for later scripts.

usage: python inventory.py FOLDER_OR_FILES... [--json inventory.json] [--gps]
"""
import argparse
import json
import os

from common import probe, proxy_of

VIDEO_EXT = {'.mp4', '.mov', '.m4v', '.mts', '.mkv', '.avi', '.insv', '.360'}


def files(args):
    out = []
    for a in args:
        if os.path.isdir(a):
            for root, _, names in os.walk(a):
                out += [os.path.join(root, n) for n in names if os.path.splitext(n)[1].lower() in VIDEO_EXT
                        and not n.startswith('._')]
        elif os.path.splitext(a)[1].lower() in VIDEO_EXT:
            out.append(a)
    return sorted(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('paths', nargs='+')
    ap.add_argument('--json', help='write the full inventory here')
    ap.add_argument('--gps', action='store_true', help='keep GPS tags in the JSON (they stay local: never publish)')
    a = ap.parse_args()
    js = a.json
    rows = []
    for f in files(a.paths):
        try:
            p = dict(probe(f))
        except RuntimeError as e:
            print('SKIP', e)
            continue
        if 'w' not in p:
            continue
        p['bytes'] = os.path.getsize(f)
        lrf = proxy_of(f)
        p['proxy'] = lrf
        notes = []
        if lrf:
            try:
                p['proxy_dur'] = probe(lrf)['dur']
                if p['proxy_dur'] - p['dur'] > 0.5:
                    notes.append(f"proxy runs {p['proxy_dur'] - p['dur']:.1f}s longer: check offsets (align_proxy.py)")
            except RuntimeError:
                pass
        if p.get('hdr'):
            notes.append(f"{p['hdr']} HDR -> hdr_to_sdr.py")
        if p['fps'] >= 47:
            notes.append(f"{p['fps']:.0f} fps: {0.5 if p['fps'] >= 59 else 0.8}x slow motion is clean")
        if p['h'] > p['w']:
            notes.append('portrait')
        if not p['audio']:
            notes.append('no sound')
        if not a.gps:
            p['location'] = None
        p['notes'] = notes
        rows.append(p)
    rows.sort(key=lambda r: (r.get('created') or '', r['path']))
    total_dur = sum(r['dur'] for r in rows)
    total_gb = sum(r['bytes'] for r in rows) / 1e9
    print(f"{'file':42s} {'created (UTC)':19s} {'len':>7s} {'size':>9s} {'fps':>6s} {'codec':>10s} "
          f"{'sound':>5s}  notes")
    for r in rows:
        name = os.path.relpath(r['path'])
        name = name if len(name) <= 42 else '…' + name[-41:]
        cr = (r.get('created') or '')[:19].replace('T', ' ')
        print(f"{name:42s} {cr:19s} {r['dur']:7.1f} {r['w']:4d}x{r['h']:<4d} {r['fps']:6.2f} "
              f"{r['codec'] + '/' + str(r['bits']):>10s} {('yes' if r['audio'] else '-'):>5s}  {'; '.join(r['notes'])}")
    print(f'{len(rows)} clips, {total_dur / 60:.1f} min, {total_gb:.1f} GB')
    if js:
        json.dump(rows, open(js, 'w'), indent=1, ensure_ascii=False)
        print('wrote', js)


if __name__ == '__main__':
    main()
