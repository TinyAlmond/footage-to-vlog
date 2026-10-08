"""Time offset between a main clip and its low-res proxy (DJI .LRF): proxy time = main time + offset.

DJI proxies can start seconds earlier than the main file and run 4-13 s longer, so in/out points read off proxy
thumbnails can miss - and the offset can change inside a clip. Compares motion signatures (tiny frame differences,
5 fps) over -8..+16 s of offset, in 8 s windows, and prints where the offset holds.

usage: python align_proxy.py MAIN.MP4 [MAIN2.MP4 ...]      (proxy = same name .LRF)
       python align_proxy.py MAIN.MP4 --proxy OTHER.LRF
"""
import argparse

from common import probe, proxy_of, proxy_offset


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('main', nargs='+')
    ap.add_argument('--proxy', help='proxy file (default: same name, .LRF)')
    a = ap.parse_args()
    for m in a.main:
        p = a.proxy or proxy_of(m)
        if not p:
            print(f'{m}: no proxy next to it')
            continue
        segs = proxy_offset(m, p)
        print(f'{m}: main {probe(m)["dur"]:.1f}s, proxy {probe(p)["dur"]:.1f}s')
        runs = []
        for t0, t1, off, c in segs:
            if runs and abs(runs[-1][2] - off) < 0.11:
                runs[-1][1] = t1
                runs[-1][3] = min(runs[-1][3], c)
            else:
                runs.append([t0, t1, off, c])
        for t0, t1, off, c in runs:
            flag = '' if c > 0.25 else '   (weak match: check by eye)'
            print(f'  main {t0:6.1f}-{t1:6.1f}s: proxy = main {off:+.1f}s  (corr >= {c:.2f}){flag}')
        if len(runs) > 1:
            print('  the offset changes inside this clip: read in/out points from the main file around the change')

if __name__ == '__main__':
    main()
