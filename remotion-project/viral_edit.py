"""
@sumnervera.ltd — Viral Short-Form Edit
Cinematic teal-orange grade, hook-first structure, animated text overlays.
"""

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import subprocess
import os
import sys

SRC = "/root/.claude/uploads/88ca9a0b-4e66-5673-a25c-8779a85e2bc0/a87e6858-a47716c1ff7b45518a4a536afcb084f2.MP4"
OUT_VIDEO_SILENT = "/tmp/viral_silent.mp4"
OUT_FINAL = "/home/user/video-use/remotion-project/public/viral_edit_sumnervera.mp4"
FFMPEG = "/usr/local/lib/python3.11/dist-packages/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2"

W, H = 480, 832
OUT_FPS = 30

os.makedirs(os.path.dirname(OUT_FINAL), exist_ok=True)

# ─── 1. Colour Grading ────────────────────────────────────────────────────────

def build_lut():
    """Precompute a teal-orange cinematic LUT for each of the 256 R/G/B levels."""
    x = np.arange(256, dtype=np.float32) / 255.0
    # Lift blacks (film look), then boost contrast
    x = np.clip(x * 0.90 + 0.05, 0, 1)
    x = np.clip((x - 0.5) * 1.20 + 0.5, 0, 1)
    # Return as uint8 curve
    return (np.clip(x, 0, 1) * 255).astype(np.uint8)

BASE_CURVE = build_lut()

def apply_grade(frame_bgr):
    b, g, r = cv2.split(frame_bgr)
    f = frame_bgr.astype(np.float32) / 255.0
    lum = 0.299 * f[:,:,2] + 0.587 * f[:,:,1] + 0.114 * f[:,:,0]

    # Apply base curve to all channels
    b = BASE_CURVE[b]; g = BASE_CURVE[g]; r = BASE_CURVE[r]
    f = cv2.merge([b, g, r]).astype(np.float32) / 255.0

    # Split-toning: warm orange highlights, cool teal shadows
    hi = np.clip((lum - 0.45) / 0.55, 0, 1)[:,:,np.newaxis]
    lo = np.clip((0.45 - lum) / 0.45, 0, 1)[:,:,np.newaxis]

    # Orange = boost R, slight G, pull B in highlights
    f[:,:,2:3] = np.clip(f[:,:,2:3] + 0.055 * hi, 0, 1)  # R
    f[:,:,1:2] = np.clip(f[:,:,1:2] + 0.015 * hi, 0, 1)  # G
    f[:,:,0:1] = np.clip(f[:,:,0:1] - 0.045 * hi, 0, 1)  # B

    # Teal = pull R, slight G, boost B in shadows
    f[:,:,2:3] = np.clip(f[:,:,2:3] - 0.035 * lo, 0, 1)
    f[:,:,1:2] = np.clip(f[:,:,1:2] + 0.015 * lo, 0, 1)
    f[:,:,0:1] = np.clip(f[:,:,0:1] + 0.040 * lo, 0, 1)

    # Saturation lift (+20%)
    lum2 = 0.299 * f[:,:,2] + 0.587 * f[:,:,1] + 0.114 * f[:,:,0]
    sat = 1.22
    for c in range(3):
        f[:,:,c] = np.clip(lum2 + sat * (f[:,:,c] - lum2), 0, 1)

    # Vignette
    cx, cy = W / 2, H / 2
    Y, X = np.ogrid[:H, :W]
    dist = np.sqrt(((X - cx) / cx) ** 2 + ((Y - cy) / cy) ** 2)
    vig = np.clip(1.0 - dist * 0.38, 0.55, 1.0)
    f *= vig[:, :, np.newaxis]

    return np.clip(f * 255, 0, 255).astype(np.uint8)


# ─── 2. Zoom helper ───────────────────────────────────────────────────────────

def zoom_frame(frame, scale):
    if abs(scale - 1.0) < 0.005:
        return frame
    h, w = frame.shape[:2]
    nh, nw = int(h / scale), int(w / scale)
    y0 = (h - nh) // 2; x0 = (w - nw) // 2
    cropped = frame[y0:y0+nh, x0:x0+nw]
    return cv2.resize(cropped, (w, h), interpolation=cv2.INTER_LANCZOS4)


# ─── 3. Text overlay ──────────────────────────────────────────────────────────

FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]

def get_font(size):
    for p in FONT_PATHS:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

def wrap_text(text, draw, font, max_w):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=font) <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines

def add_text_overlay(frame_bgr, text, position="top", size=32, alpha=1.0, style="hook"):
    """
    position: 'top' | 'bottom' | 'center'
    style: 'hook' (large white caps) | 'caption' (smaller subtitle) | 'brand' (spaced)
    """
    if not text.strip():
        return frame_bgr

    pil = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)).convert("RGBA")
    overlay = Image.new("RGBA", pil.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font = get_font(size)
    max_w = W - 48
    lines = wrap_text(text, draw, font, max_w)
    line_h = size + 8
    total_h = len(lines) * line_h + 12

    if position == "top":
        start_y = 28
    elif position == "bottom":
        start_y = H - total_h - 48
    else:
        start_y = (H - total_h) // 2

    # Draw backdrop pill
    pad = 12
    box_top = start_y - pad
    box_bot = start_y + total_h
    box_w_max = max(
        draw.textlength(l, font=font) for l in lines
    ) + pad * 2
    box_left = (W - box_w_max) // 2

    if style == "caption":
        draw.rounded_rectangle(
            [box_left, box_top, box_left + box_w_max, box_bot],
            radius=8,
            fill=(0, 0, 0, int(165 * alpha))
        )
    # hook/brand: no box, just shadow

    for i, line in enumerate(lines):
        tw = draw.textlength(line, font=font)
        x = (W - tw) // 2
        y = start_y + i * line_h

        if style in ("hook", "brand"):
            # Thick shadow
            for dx, dy in [(-2,-2),(2,-2),(-2,2),(2,2),(0,3),(3,0),(-3,0),(0,-3)]:
                draw.text((x+dx, y+dy), line, font=font, fill=(0,0,0,int(220*alpha)))
        else:
            draw.text((x+1, y+1), line, font=font, fill=(0,0,0,int(180*alpha)))

        if style == "brand":
            draw.text((x, y), line, font=font, fill=(255, 220, 180, int(255*alpha)))
        else:
            draw.text((x, y), line, font=font, fill=(255, 255, 255, int(255*alpha)))

    merged = Image.alpha_composite(pil, overlay)
    return cv2.cvtColor(np.array(merged.convert("RGB")), cv2.COLOR_RGB2BGR)


# ─── 4. Transition helpers ────────────────────────────────────────────────────

def crossfade(frame_a, frame_b, t):
    """t: 0.0 → frame_a, 1.0 → frame_b"""
    return np.clip(frame_a * (1-t) + frame_b * t, 0, 255).astype(np.uint8)


# ─── 5. Load all source frames into memory ────────────────────────────────────

print("Loading source frames…")
cap = cv2.VideoCapture(SRC)
SRC_FPS = cap.get(cv2.CAP_PROP_FPS)   # ~40.3
SRC_TOTAL = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))  # 930
print(f"  Source: {W}×{H} @ {SRC_FPS:.1f}fps, {SRC_TOTAL} frames")

src_frames = []
while True:
    ret, frm = cap.read()
    if not ret:
        break
    src_frames.append(frm)
cap.release()
print(f"  Loaded {len(src_frames)} frames")


# ─── 6. Scene definition ──────────────────────────────────────────────────────
# Each scene: dict of settings. src frames are at SRC_FPS.
# t0/t1 are in SECONDS in source video.
# speed: >1 = faster, <1 = slow-mo
# zoom_s / zoom_e: scale factor at start/end of scene (>1 = punched in)
# text_cfg: list of (text, position, style, size, t_start, t_end) within scene seconds

def sec_to_src(t):
    return int(round(t * SRC_FPS))

XFADE_FRAMES = 10  # output frames for cross-dissolve between scenes

scenes = [
    # ── HOOK (0–3.5s) ──────────────────────────────────────────────────────
    # Start with the MONEY SHOT: box tower reveal, slowed
    dict(
        t0=21.5, t1=23.07, speed=0.55,
        zoom_s=1.22, zoom_e=1.35,
        texts=[
            ("POV: you just found", "top", "hook", 30, 0.0, 1.5),
            ("@sumnervera.ltd", "bottom", "brand", 38, 0.6, 3.5),
        ]
    ),
    # ── AUTHORITY (3.5–6s) ─────────────────────────────────────────────────
    # Exterior balcony — London townhouse establishes prestige
    dict(
        t0=0.0, t1=2.0, speed=1.0,
        zoom_s=1.3, zoom_e=1.08,
        texts=[
            ("London's most curated luxury edit", "bottom", "caption", 26, 0.3, 2.0),
        ]
    ),
    # ── PRODUCT / VOICE (6–12s) ────────────────────────────────────────────
    # Living room — she's speaking with the candle
    dict(
        t0=7.0, t1=12.0, speed=1.0,
        zoom_s=1.05, zoom_e=1.12,
        texts=[
            ("Not resale. Curation.", "top", "hook", 28, 1.5, 3.5),
        ]
    ),
    # ── STAIRCASE / LIFESTYLE (12–17s) ─────────────────────────────────────
    # Most visually stunning scene — let it breathe, no text
    dict(
        t0=12.0, t1=17.0, speed=1.0,
        zoom_s=1.12, zoom_e=1.02,
        texts=[]
    ),
    # ── LUXURY HAUL REVEAL (17–22s) ────────────────────────────────────────
    # Table full of boxes — boxes reveal + Chanel
    dict(
        t0=17.0, t1=22.0, speed=1.0,
        zoom_s=1.0, zoom_e=1.18,
        texts=[
            ("Cartier. Chanel. Amina Muaddi. Rolex.", "bottom", "caption", 23, 1.0, 4.0),
        ]
    ),
    # ── OUTRO CTA (final 2s) ───────────────────────────────────────────────
    # Box tower again, slower, final brand stamp
    dict(
        t0=22.0, t1=23.07, speed=0.5,
        zoom_s=1.35, zoom_e=1.5,
        texts=[
            ("Follow for weekly drops", "top", "caption", 24, 0.0, 1.5),
            ("@sumnervera.ltd", "bottom", "brand", 44, 0.2, 2.2),
        ]
    ),
]


# ─── 7. Render output frames ──────────────────────────────────────────────────

def lerp(a, b, t):
    return a + (b - a) * t

def ease_in_out(t):
    return t * t * (3 - 2 * t)

print("Rendering output frames…")

# VideoWriter (H.264-compatible mp4v for mp4)
fourcc = cv2.VideoWriter_fourcc(*'mp4v')
writer = cv2.VideoWriter(OUT_VIDEO_SILENT, fourcc, OUT_FPS, (W, H))

rendered_scene_frames = []  # list of lists, for cross-fade access

for scene_idx, scene in enumerate(scenes):
    t0, t1, speed = scene["t0"], scene["t1"], scene["speed"]
    zoom_s, zoom_e = scene["zoom_s"], scene["zoom_e"]
    texts = scene["texts"]

    src0 = sec_to_src(t0)
    src1 = min(sec_to_src(t1), len(src_frames) - 1)

    # Build list of source frame indices at the desired speed
    raw_src_indices = list(range(src0, src1 + 1))
    src_count = len(raw_src_indices)
    natural_out_frames = int(src_count / SRC_FPS * OUT_FPS)
    if natural_out_frames < 1:
        natural_out_frames = 1

    # Adjust for speed
    out_frame_count = int(natural_out_frames / speed)
    if out_frame_count < 2:
        out_frame_count = 2

    scene_duration_out = out_frame_count / OUT_FPS  # in output seconds

    print(f"  Scene {scene_idx+1}: src[{src0}–{src1}] → {out_frame_count} out-frames ({scene_duration_out:.1f}s)")

    scene_out_frames = []

    for out_i in range(out_frame_count):
        # Map output frame → source frame index
        out_frac = out_i / max(out_frame_count - 1, 1)
        src_frac = out_frac  # linear
        src_idx = src0 + int(src_frac * (src1 - src0))
        src_idx = min(src_idx, len(src_frames) - 1)

        frame = src_frames[src_idx].copy()

        # Resize to W×H if needed
        if frame.shape[1] != W or frame.shape[0] != H:
            frame = cv2.resize(frame, (W, H))

        # Apply colour grade
        frame = apply_grade(frame)

        # Zoom (ease-in-out)
        t_ease = ease_in_out(out_frac)
        zoom = lerp(zoom_s, zoom_e, t_ease)
        frame = zoom_frame(frame, zoom)

        # Text overlays
        out_t = out_frac * scene_duration_out  # time within scene (output seconds)
        for (txt, pos, style, sz, ta, tb) in texts:
            if ta <= out_t <= tb:
                dur = tb - ta
                # Fade in first 0.3s, fade out last 0.3s
                alpha = 1.0
                elapsed = out_t - ta
                if elapsed < 0.3:
                    alpha = elapsed / 0.3
                elif (dur - elapsed) < 0.3:
                    alpha = (dur - elapsed) / 0.3
                frame = add_text_overlay(frame, txt, pos, sz, alpha, style)

        scene_out_frames.append(frame)

    rendered_scene_frames.append(scene_out_frames)

# Write frames with cross-fades between scenes
print("Writing frames with transitions…")

for scene_idx, scene_frames in enumerate(rendered_scene_frames):
    is_last = scene_idx == len(rendered_scene_frames) - 1
    next_frames = rendered_scene_frames[scene_idx + 1] if not is_last else None

    for fi, frame in enumerate(scene_frames):
        # Cross-fade zone at the END of this scene
        if not is_last and fi >= len(scene_frames) - XFADE_FRAMES:
            fade_i = fi - (len(scene_frames) - XFADE_FRAMES)
            t = (fade_i + 1) / XFADE_FRAMES
            next_frame = next_frames[min(fade_i, len(next_frames) - 1)]
            frame = crossfade(frame, next_frame, t)

        writer.write(frame)

writer.release()
print(f"Silent video written → {OUT_VIDEO_SILENT}")


# ─── 8. Mux audio from source ─────────────────────────────────────────────────
# We need to map the output timeline back to source audio.
# Since we reordered scenes and changed speeds, we'll build a complex filter.
# For simplicity: extract audio segments and concatenate with matching durations.

print("Muxing audio from source segments…")

# Build ffmpeg filter_complex for audio
# Each scene maps a source time range → output duration
audio_segments = []
for s in scenes:
    speed = s["speed"]
    src_dur = s["t1"] - s["t0"]
    out_dur = src_dur / speed
    audio_segments.append({
        "ss": s["t0"],
        "to": s["t1"],
        "speed": speed,
        "out_dur": out_dur,
    })

# Build ffmpeg command to assemble audio
# Strategy: trim each segment from source, apply atempo for speed, concat
filter_parts = []
concat_labels = []

for i, seg in enumerate(audio_segments):
    # atempo range is [0.5, 2.0]; for speeds outside range, chain multiple
    spd = seg["speed"]
    # Build atempo chain
    if spd >= 0.5 and spd <= 2.0:
        atempo_chain = f"atempo={spd:.4f}"
    elif spd < 0.5:
        # e.g. speed=0.4 → atempo=0.5,atempo=0.8
        atempo_chain = f"atempo=0.5,atempo={spd/0.5:.4f}"
    else:
        atempo_chain = f"atempo=2.0,atempo={spd/2.0:.4f}"

    lbl = f"a{i}"
    filter_parts.append(
        f"[0:a]atrim=start={seg['ss']:.4f}:end={seg['to']:.4f},"
        f"asetpts=PTS-STARTPTS,{atempo_chain}[{lbl}]"
    )
    concat_labels.append(f"[{lbl}]")

n = len(audio_segments)
concat_filter = "".join(concat_labels) + f"concat=n={n}:v=0:a=1[aout]"
filter_parts.append(concat_filter)
full_filter = ";".join(filter_parts)

cmd = [
    FFMPEG, "-y",
    "-i", OUT_VIDEO_SILENT,
    "-i", SRC,
    "-filter_complex", full_filter,
    "-map", "0:v",
    "-map", "[aout]",
    "-c:v", "libx264", "-preset", "fast", "-crf", "18",
    "-c:a", "aac", "-b:a", "192k",
    "-shortest",
    OUT_FINAL,
]

print("  Running ffmpeg to mux and encode…")
result = subprocess.run(cmd, capture_output=True, text=True)
if result.returncode != 0:
    print("ffmpeg stderr:", result.stderr[-2000:])
    print("Falling back to video-only output…")
    # Just copy the silent video
    import shutil
    shutil.copy(OUT_VIDEO_SILENT, OUT_FINAL)
else:
    print(f"Final video → {OUT_FINAL}")

print("Done.")
