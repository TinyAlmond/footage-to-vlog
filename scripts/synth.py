"""Small additive/subtractive synth kit for original scores: pad, pluck, kalimba, bass, shaker, kick, clap; noise
sweeps for risers and whooshes; convolution reverb; the 'heard from under water' treatment and bubbles; BS.1770
loudness and an oversampled lookahead limiter. Everything 48 kHz stereo float64; `add` mixes a mono or stereo event
into a buffer at a time in seconds."""
import numpy as np
from scipy import ndimage as ndi
from scipy import signal

SR = 48000
rng = np.random.default_rng(7)


def hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def env_adsr(n, a, d, s, r, hold):
    tt = np.arange(n) / SR
    e = np.where(tt < a, tt / max(a, 1e-4), s + (1 - s) * np.exp(-(tt - a) / max(d, 1e-4)))
    rel = tt > hold
    e[rel] *= np.exp(-(tt[rel] - hold) / max(r, 1e-4))
    return e


def add(buf, start, x, pan=0.0, gain=1.0):
    i = int(round(start * SR))
    if i < 0:
        x, i = x[-i:], 0
    if i >= len(buf) or len(x) == 0:
        return
    x = x[:len(buf) - i] * gain
    if x.ndim == 2:
        buf[i:i + len(x)] += x
        return
    gl, gr = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
    buf[i:i + len(x), 0] += x * gl
    buf[i:i + len(x), 1] += x * gr


def pad_note(m, dur, attack=0.9, cutoff=1500):
    n = int((dur + 1.6) * SR)
    tt = np.arange(n) / SR
    x = np.zeros(n)
    for c in (-9, 0, 8):
        x += 2 * ((hz(m + c / 100) * tt + rng.random()) % 1.0) - 1
    b, a = signal.butter(2, cutoff / (SR / 2))
    return signal.lfilter(b, a, x) / 3 * env_adsr(n, attack, 2.0, 0.85, 0.9, dur)


def pluck(m, dur=1.2, bright=1.0):
    n = int(dur * SR)
    tt = np.arange(n) / SR
    f = hz(m)
    x = np.zeros(n)
    for k in range(1, 12):
        if k * f > 12000:
            break
        x += (1 / k ** 1.3) * np.sin(2 * np.pi * k * f * tt + rng.random()) * np.exp(-tt * (2.2 + 1.9 * k / bright))
    return 0.45 * x * np.minimum(1, tt / 0.003)


def kalimba(m, dur=1.6):
    n = int(dur * SR)
    tt = np.arange(n) / SR
    f = hz(m)
    x = np.sin(2 * np.pi * f * tt) * np.exp(-tt / 0.55)
    x += 0.30 * np.sin(2 * np.pi * 2.0 * f * tt) * np.exp(-tt / 0.25)
    x += 0.18 * np.sin(2 * np.pi * 5.4 * f * tt) * np.exp(-tt / 0.06)
    b, a = signal.butter(2, 3000 / (SR / 2), 'high')
    x += 0.05 * signal.lfilter(b, a, rng.normal(0, 1, n) * np.exp(-tt / 0.004))
    return 0.6 * x * np.minimum(1, tt / 0.002)


def bass(m, dur, bright=0.25):
    n = int((dur + 0.4) * SR)
    tt = np.arange(n) / SR
    f = hz(m)
    tone = np.sin(2 * np.pi * f * tt) + bright * np.sin(2 * np.pi * 2 * f * tt)
    return 0.55 * tone * env_adsr(n, 0.015, 0.5, 0.6, 0.25, dur)


def shaker(vel):
    n = int(0.09 * SR)
    tt = np.arange(n) / SR
    b, a = signal.butter(2, [5500 / (SR / 2), 11000 / (SR / 2)], 'band')
    return vel * signal.lfilter(b, a, rng.normal(0, 1, n)) * (np.minimum(1, tt / 0.006) * np.exp(-tt / 0.03))


def kick(depth=1.0):
    n = int(0.4 * SR)
    tt = np.arange(n) / SR
    return 0.8 * np.sin(2 * np.pi * np.cumsum(46 + 75 * depth * np.exp(-tt / 0.04)) / SR) * np.exp(-tt / 0.2)


def clap():
    n = int(0.25 * SR)
    tt = np.arange(n) / SR
    b, a = signal.butter(2, [900 / (SR / 2), 4000 / (SR / 2)], 'band')
    x = signal.lfilter(b, a, rng.normal(0, 1, n))
    env = np.zeros(n)
    for d in (0.0, 0.011, 0.022):                       # the three slaps of a hand clap
        env += np.where(tt >= d, np.exp(-np.maximum(tt - d, 0) / 0.006), 0)
    env += 0.5 * np.exp(-tt / 0.08)
    return 0.5 * x * env


def noise_burst(dur, hp, tau, attack=0.002):
    n = int(dur * SR)
    tt = np.arange(n) / SR
    b, a = signal.butter(2, hp / (SR / 2), 'high')
    return signal.lfilter(b, a, rng.normal(0, 1, n)) * np.minimum(1, tt / attack) * np.exp(-tt / tau)


def sweep(dur, f0, f1, env):
    """noise through a one-pole low-pass whose cutoff moves exponentially f0 -> f1; env(u), u in [0, 1)"""
    n = int(dur * SR)
    fc = f0 * (f1 / f0) ** (np.arange(n) / n)
    g = 1 - np.exp(-2 * np.pi * fc / SR)
    x = rng.normal(0, 1, n)
    y = np.empty(n)
    z = 0.0
    for k in range(n):
        z += g[k] * (x[k] - z)
        y[k] = z
    return y * env(np.arange(n) / n)


def ir(rt60, pre=0.02, lp=6000, seed=0):
    r = np.random.default_rng(seed)
    n = int((rt60 * 1.2 + pre) * SR)
    tt = np.arange(n) / SR
    x = r.normal(0, 1, (n, 2)) * np.exp(-6.9 * tt / rt60)[:, None]
    x[:int(pre * SR)] = 0
    b, a = signal.butter(1, lp / (SR / 2))
    x = signal.lfilter(b, a, x, axis=0)
    return x / np.sqrt((x ** 2).sum(0))


def reverb(x, rt60, wet, lp, seed):
    h = ir(rt60, lp=lp, seed=seed)
    y = np.stack([signal.fftconvolve(x[:, c], h[:, c])[:len(x)] for c in range(2)], 1)
    return (1 - wet) * x + wet * y * 3.0


def lufs(x):
    """ITU-R BS.1770-4 integrated loudness at 48 kHz"""
    x = x[:, None] if x.ndim == 1 else x
    y = signal.lfilter([1.53512485958697, -2.69169618940638, 1.19839281085285],
                       [1.0, -1.69065929318241, 0.73248077421585], x, axis=0)
    y = signal.lfilter([1.0, -2.0, 1.0], [1.0, -1.99004745483398, 0.99007225036621], y, axis=0)
    p = np.concatenate([[0], np.cumsum((y ** 2).sum(1))])
    blk, hop = int(0.4 * SR), int(0.1 * SR)
    if len(y) < blk:
        return -70.0
    st = np.arange(0, len(y) - blk + 1, hop)
    ms = (p[st + blk] - p[st]) / blk
    lv = -0.691 + 10 * np.log10(ms + 1e-15)
    g = ms[lv > -70]
    if not len(g):
        return -70.0
    rel = -0.691 + 10 * np.log10(g.mean()) - 10
    return float(-0.691 + 10 * np.log10(ms[(lv > -70) & (lv > rel)].mean()))


def limiter(x, ceil_db=-1.5, look=0.02):
    """oversampled-peak lookahead limiter"""
    up = signal.resample_poly(x, 4, 1, axis=0)
    pk = np.abs(up).max(1)[:len(x) * 4].reshape(-1, 4).max(1)
    pk = np.pad(pk, (0, len(x) - len(pk)), mode='edge')
    req = np.minimum(1.0, 10 ** (ceil_db / 20) / np.maximum(pk, 1e-9))
    L = int(look * SR)
    g = ndi.uniform_filter1d(ndi.minimum_filter1d(req, 2 * L + 1), L)
    return x * g[:, None], float(g.min())


def peaking(f0, gain_db, q):
    """biquad peaking EQ (b, a)"""
    A = 10 ** (gain_db / 40)
    w = 2 * np.pi * f0 / SR
    al = np.sin(w) / (2 * q)
    b = np.array([1 + al * A, -2 * np.cos(w), 1 - al * A])
    a = np.array([1 + al / A, -2 * np.cos(w), 1 - al / A])
    return b / a[0], a / a[0]


def underwater(x, cutoff=480.0):
    """music heard from below the surface: long wet reverb, steep zero-phase low-pass (48 dB/oct), a 'pressure' bump
    at 250 Hz, slow pitch and level wobble. A gentle 850 Hz low-pass alone does not read as under water."""
    n = len(x)
    t = np.arange(n) / SR
    uw = reverb(x, 3.6, 0.55, 1800, 2)
    b, a = signal.butter(4, cutoff / (SR / 2))
    uw = signal.filtfilt(b, a, uw, axis=0)
    b, a = peaking(250, 4.0, 0.8)
    uw = signal.lfilter(b, a, uw, axis=0)
    d = (0.0025 * SR) * (1 + np.sin(2 * np.pi * 0.3 * t))
    idx = np.clip(np.arange(n) - d, 0, n - 1)
    uw = np.stack([np.interp(idx, np.arange(n), uw[:, c]) for c in range(2)], 1)
    return uw * (1 + 0.12 * np.sin(2 * np.pi * 0.5 * t))[:, None]


def bubble(f0, rise, dur, tau):
    n = int(dur * SR)
    tt = np.arange(n) / SR
    f = f0 * rise ** (tt / dur)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.minimum(1, tt / 0.002) * np.exp(-tt / tau)


def bubbles(buf, tc, count, spread, base, gain=1.0):
    """a cluster of exhaled bubbles around time tc"""
    for _ in range(count):
        tb = tc + rng.random() * spread
        x = bubble(base * (0.7 + 0.6 * rng.random()), 1.4 + 0.6 * rng.random(), 0.04 + 0.05 * rng.random(),
                   0.012 + 0.018 * rng.random())
        add(buf, tb, x * (0.25 + 0.35 * rng.random()) * gain, pan=rng.uniform(-0.6, 0.6))


def plunge():
    """into the water: noise whose cutoff falls fast"""
    n = int(0.75 * SR)
    tt = np.arange(n) / SR
    return _moving_lowpass(rng.normal(0, 1, n), 4000 * np.exp(-tt / 0.18) + 250) * \
        np.minimum(1, tt / 0.03) * np.exp(-tt / 0.32) * 1.6


def swish():
    """out of the water: noise whose cutoff rises"""
    n = int(0.75 * SR)
    tt = np.arange(n) / SR
    return _moving_lowpass(rng.normal(0, 1, n), 300 + 3500 * (tt / 0.75)) * \
        np.minimum(1, tt / 0.25) * np.exp(-np.maximum(tt - 0.25, 0) / 0.2) * 1.6


def _moving_lowpass(x, fc):
    y = np.empty(len(x))
    z = 0.0
    g = 1 - np.exp(-2 * np.pi * fc / SR)
    for k in range(len(x)):
        z += g[k] * (x[k] - z)
        y[k] = z
    return y


def whoosh(dur=0.55, direction=1):
    """stereo whoosh that crosses the field (direction 1: left -> right) - for a whip pan"""
    n = int(dur * SR)
    u = np.arange(n) / n
    w = sweep(dur, 600, 5000, lambda v: np.sin(np.pi * v) ** 2)
    pan = u if direction > 0 else 1 - u
    return np.stack([w * np.cos(pan * np.pi / 2), w * np.sin(pan * np.pi / 2)], 1)
