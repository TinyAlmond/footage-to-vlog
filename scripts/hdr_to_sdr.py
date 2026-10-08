"""Phone HDR video (HLG / Dolby Vision, PQ) -> SDR BT.709, before editing.

Left as HDR, a phone clip decodes flat and grey next to SDR camera footage (and every grade on it is wrong).
macOS: avconvert (Apple's own tone mapping, the same as Photos' export; keeps the frame rate and sound).
Elsewhere: ffmpeg zscale + tonemap (needs an ffmpeg built with libzimg). SDR files are skipped.

usage: python hdr_to_sdr.py CLIP... --out sdr/ [--size 1080|2160]
"""
import argparse
import os
import shutil
import subprocess

from common import DARWIN, probe

PRESET = {1080: 'Preset1920x1080', 2160: 'Preset3840x2160', 720: 'Preset1280x720'}


def has_zscale():
    out = subprocess.run(['ffmpeg', '-hide_banner', '-filters'], capture_output=True, text=True).stdout
    return ' zscale ' in out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('clips', nargs='+')
    ap.add_argument('--out', required=True)
    ap.add_argument('--size', type=int, choices=sorted(PRESET), help='output height (default: the source size)')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    for c in a.clips:
        p = probe(c)
        if not p.get('hdr'):
            print(f'{c}: SDR already, skipped')
            continue
        dst = os.path.join(a.out, os.path.splitext(os.path.basename(c))[0] + '.mov')
        h = a.size or min(PRESET, key=lambda k: abs(k - min(p['w'], p['h'])))
        if DARWIN and shutil.which('avconvert'):
            subprocess.run(['avconvert', '--source', c, '--output', dst, '--preset', PRESET[h], '--replace'],
                           check=True, capture_output=True)
        elif has_zscale():
            vf = (f'zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=hable:desat=0,'
                  f'zscale=t=bt709:m=bt709:r=tv,format=yuv420p,scale=-2:{h}')
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', c, '-vf', vf, '-c:v', 'libx264', '-crf', '16',
                            '-preset', 'medium', '-color_primaries', 'bt709', '-color_trc', 'bt709',
                            '-colorspace', 'bt709', '-c:a', 'copy', dst], check=True)
        else:
            raise SystemExit('no avconvert (macOS) and this ffmpeg has no zscale: install an ffmpeg with libzimg')
        q = probe(dst)
        print(f"{c}: {p['hdr']} -> {dst}  {q['w']}x{q['h']} {q['fps']:.2f} fps, "
              f"transfer {q.get('transfer') or 'bt709'}, {q['dur']:.1f}s (source {p['dur']:.1f}s)")


if __name__ == '__main__':
    main()
