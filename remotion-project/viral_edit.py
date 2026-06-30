"""
@sumnervera.ltd — Polished edit, original order kept.
Applies: cinematic grade, exposure fix on dark section,
         subtle zoom drift, smooth crossfades at scene cuts,
         original audio copied through untouched.
"""

import cv2
import numpy as np
import subprocess, os, shutil

SRC    = "/root/.claude/uploads/88ca9a0b-4e66-5673-a25c-8779a85e2bc0/a87e6858-a47716c1ff7b45518a4a536afcb084f2.MP4"
SILENT = "/tmp/viral_silent_v2.mp4"
OUT    = "/home/user/video-use/remotion-project/public/viral_edit_sumnervera.mp4"
FFMPEG = "/usr/local/lib/python3.11/dist-packages/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2"

W, H, OUT_FPS = 480, 832, 30

os.makedirs(os.path.dirname(OUT), exist_ok=True)


# ── 1. Pre-computed LUT for base tone curve ───────────────────────────────────

def make_curve():
    x = np.arange(256, dtype=np.float32) / 255.0
    x = np.clip(x * 0.91 + 0.045, 0, 1)          # lift blacks, rein in whites
    x = np.clip((x - 0.5) * 1.18 + 0.5, 0, 1)    # contrast
    return (x * 255).astype(np.uint8)

CURVE = make_curve()


# ── 2. Per-frame colour grade ─────────────────────────────────────────────────

def apply_grade(frame_bgr, exposure_boost=1.0):
    b, g, r = cv2.split(frame_bgr)
    b, g, r = CURVE[b], CURVE[g], CURVE[r]
    f = cv2.merge([b, g, r]).astype(np.float32) / 255.0

    if exposure_boost != 1.0:
        f = np.clip(f * exposure_boost, 0, 1)

    lum = 0.299*f[:,:,2] + 0.587*f[:,:,1] + 0.114*f[:,:,0]

    # Teal-orange split toning
    hi = np.clip((lum - 0.42) / 0.58, 0, 1)[:,:,None]
    lo = np.clip((0.42 - lum) / 0.42, 0, 1)[:,:,None]
    f[:,:,2:3] = np.clip(f[:,:,2:3] + 0.050*hi - 0.030*lo, 0, 1)  # R
    f[:,:,1:2] = np.clip(f[:,:,1:2] + 0.012*hi + 0.012*lo, 0, 1)  # G
    f[:,:,0:1] = np.clip(f[:,:,0:1] - 0.040*hi + 0.038*lo, 0, 1)  # B

    # Saturation +18%
    lum2 = 0.299*f[:,:,2] + 0.587*f[:,:,1] + 0.114*f[:,:,0]
    s = 1.18
    for c in range(3):
        f[:,:,c] = np.clip(lum2 + s*(f[:,:,c]-lum2), 0, 1)

    # Vignette
    cx, cy = W/2, H/2
    Y, X = np.ogrid[:H, :W]
    dist = np.sqrt(((X-cx)/cx)**2 + ((Y-cy)/cy)**2)
    vig = np.clip(1.0 - dist*0.35, 0.58, 1.0)
    f *= vig[:,:,None]

    return np.clip(f*255, 0, 255).astype(np.uint8)


# ── 3. Zoom/crop helper ───────────────────────────────────────────────────────

def zoom_frame(frame, scale):
    if abs(scale - 1.0) < 0.004:
        return frame
    h, w = frame.shape[:2]
    nh, nw = int(h/scale), int(w/scale)
    y0, x0 = (h-nh)//2, (w-nw)//2
    return cv2.resize(frame[y0:y0+nh, x0:x0+nw], (w, h),
                      interpolation=cv2.INTER_LANCZOS4)


# ── 4. Load source frames ─────────────────────────────────────────────────────

print("Loading source frames…")
cap = cv2.VideoCapture(SRC)
SRC_FPS   = cap.get(cv2.CAP_PROP_FPS)          # ~40.3
SRC_TOTAL = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))  # 930
print(f"  {W}×{H}  {SRC_FPS:.1f}fps  {SRC_TOTAL} frames  ({SRC_TOTAL/SRC_FPS:.1f}s)")

src = []
while True:
    ok, frm = cap.read()
    if not ok:
        break
    src.append(frm)
cap.release()
print(f"  Loaded {len(src)} frames")


# ── 5. Scene map (ORIGINAL ORDER, no reordering) ─────────────────────────────
# t0/t1 in source seconds.
# zoom_s/zoom_e: subtle drift — stays close to 1.0, never aggressive.
# exposure: >1.0 brightens dark sections.

scenes = [
    # Exterior balcony — elegant opening
    dict(t0=0.0,  t1=2.0,  zoom_s=1.12, zoom_e=1.04, exposure=1.0),
    # Garden walk / outdoor transition
    dict(t0=2.0,  t1=4.0,  zoom_s=1.04, zoom_e=1.10, exposure=1.05),
    # Dark indoor transition — boost exposure to rescue this section
    dict(t0=4.0,  t1=7.0,  zoom_s=1.10, zoom_e=1.04, exposure=1.55),
    # Living room, candle, speaking to camera
    dict(t0=7.0,  t1=12.0, zoom_s=1.04, zoom_e=1.10, exposure=1.0),
    # Staircase — most cinematic scene, let it breathe
    dict(t0=12.0, t1=17.0, zoom_s=1.10, zoom_e=1.02, exposure=1.0),
    # Table with boxes — building to reveal
    dict(t0=17.0, t1=22.0, zoom_s=1.02, zoom_e=1.10, exposure=1.0),
    # Final reveal — luxury tower + brand handle
    dict(t0=22.0, t1=23.07,zoom_s=1.10, zoom_e=1.18, exposure=1.0),
]

XFADE = 12   # cross-dissolve length in output frames


# ── 6. Render ─────────────────────────────────────────────────────────────────

def ease(t):
    return t*t*(3 - 2*t)

def lerp(a, b, t):
    return a + (b-a)*t

print("Rendering…")
fourcc = cv2.VideoWriter_fourcc(*'mp4v')
writer = cv2.VideoWriter(SILENT, fourcc, OUT_FPS, (W, H))

rendered = []   # each entry: list of processed frames for that scene

for si, sc in enumerate(scenes):
    t0, t1 = sc["t0"], sc["t1"]
    zs, ze  = sc["zoom_s"], sc["zoom_e"]
    exp     = sc["exposure"]

    f0 = int(round(t0 * SRC_FPS))
    f1 = min(int(round(t1 * SRC_FPS)), len(src)-1)

    # Output frame count: keep source timing (no speed change)
    out_n = int((f1 - f0) / SRC_FPS * OUT_FPS)
    out_n = max(out_n, 2)

    print(f"  Scene {si+1}: src[{f0}–{f1}]  →  {out_n} out-frames  "
          f"(exp×{exp:.2f}, zoom {zs:.2f}→{ze:.2f})")

    frames = []
    for oi in range(out_n):
        frac   = oi / max(out_n-1, 1)
        src_i  = f0 + int(frac * (f1-f0))
        src_i  = min(src_i, len(src)-1)
        frame  = src[src_i].copy()
        if frame.shape[1] != W or frame.shape[0] != H:
            frame = cv2.resize(frame, (W, H))
        frame  = apply_grade(frame, exposure_boost=exp)
        zoom   = lerp(zs, ze, ease(frac))
        frame  = zoom_frame(frame, zoom)
        frames.append(frame)

    rendered.append(frames)

# Write with cross-dissolves
print("Writing with cross-dissolves…")
for si, frames in enumerate(rendered):
    nxt = rendered[si+1] if si < len(rendered)-1 else None
    for fi, frm in enumerate(frames):
        if nxt and fi >= len(frames) - XFADE:
            xi  = fi - (len(frames) - XFADE)
            t   = (xi+1) / XFADE
            nf  = nxt[min(xi, len(nxt)-1)]
            frm = np.clip(frm*(1-t) + nf*t, 0, 255).astype(np.uint8)
        writer.write(frm)

writer.release()
print(f"Silent video → {SILENT}")


# ── 7. Copy original audio through untouched ─────────────────────────────────
# Since we kept the original order and timing, audio maps 1:1.
# ffmpeg: take video from silent file, audio from source, re-encode video to H.264.

print("Muxing original audio…")
cmd = [
    FFMPEG, "-y",
    "-i", SILENT,
    "-i", SRC,
    "-map", "0:v",
    "-map", "1:a",
    "-c:v", "libx264", "-preset", "fast", "-crf", "17",
    "-c:a", "copy",
    "-shortest",
    OUT,
]
res = subprocess.run(cmd, capture_output=True, text=True)
if res.returncode != 0:
    print("ffmpeg error:", res.stderr[-1500:])
    shutil.copy(SILENT, OUT)
    print("Fell back to silent copy.")
else:
    print(f"Final video → {OUT}")

print("Done.")
