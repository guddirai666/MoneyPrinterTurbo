#!/usr/bin/env python3
"""Assemble 'The Visionary' — a 14-scene, 9:16 vertical short.

Pipeline (all local, ffmpeg + Pillow):
  scenes    : still image -> 8s clip with the shot-list camera move
  scenes-av : + per-scene dialogue mix and burned-in subtitles
  final     : concat all scenes, mix background music -> output/*.mp4

Usage: python3 assemble.py [scenes|scenes-av|final|all]
"""
import os
import re
import subprocess
import sys

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

FF = imageio_ffmpeg.get_ffmpeg_exe()
W, H, FPS, DUR = 1080, 1920, 30, 8.0
N = int(FPS * DUR)  # 240 frames per scene
FONT_PATH = "resource/fonts/BeVietnamPro-Bold.ttf"
BGM = "resource/songs/output000.mp3"
WORK = "work"
os.makedirs(WORK, exist_ok=True)
os.makedirs("output", exist_ok=True)


def run(cmd):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True)


def duration(path):
    out = subprocess.run(
        [FF, "-hide_banner", "-i", path], capture_output=True, text=True
    ).stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
    if not m:
        return 0.0
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


# (scene, camera move from the shot list, [(audio, speaker, spoken text)])
SCENES = [
    (1, "push", [("assets/audio/s01_pig.mp3", "PIG",
                 "Dinner in minutes. Pure chicken genius.")]),
    (2, "locked", [("assets/audio/s02_wolf.mp3", "WOLF",
                    "Chicken genius. Yours?")]),
    (3, "push", [("assets/audio/s03_pig.mp3", "PIG",
                 "I heat 'em. I plate 'em. I'm a visionary.")]),
    (4, "pan", [("assets/audio/s04_tito.mp3", "TITO", "Did you invent these?"),
               ("assets/audio/s04_pig.mp3", "PIG", "I improved dinner.")]),
    (5, "push", [("assets/audio/s05_wolf.mp3", "WOLF",
                 "Read the smallest words."),
                ("assets/audio/s05_pig.mp3", "PIG",
                 "Chicken. Water. Seasoning. Breading. Who cares?")]),
    (6, "locked", [("assets/audio/s06_wolf.mp3", "WOLF",
                    "Who made chicken convenient?"),
                  ("assets/audio/s06_tito.mp3", "TITO", "Not him?")]),
    (7, "pan_rev", [("assets/audio/s07_wolf.mp3", "WOLF (V.O.)",
                     "Cornell University. Robert C. Baker studies poultry.")]),
    (8, "locked", [("assets/audio/s08_wolf.mp3", "WOLF (V.O.)",
                    "Nineteen sixty-three. Baker and Joseph Marshall propose a chicken stick.")]),
    (9, "push", [("assets/audio/s09_wolf.mp3", "WOLF (V.O.)",
                  "Ground chicken. A coating that stays put.")]),
    (10, "pan", [("assets/audio/s10_wolf.mp3", "WOLF (V.O.)",
                  "Nineteen eighty-three. McDonald's takes McNuggets nationwide.")]),
    (11, "push", [("assets/audio/s11_wolf.mp3", "WOLF (V.O.)",
                   "Convenience has a long history.")]),
    (12, "locked", [("assets/audio/s12_pig.mp3", "PIG", "I picked the sauce."),
                    ("assets/audio/s12_wolf.mp3", "WOLF", "A visionary.")]),
    (13, "push", [("assets/audio/s13_tito.mp3", "TITO",
                   "Shh, not another word. Found the professor.")]),
    (14, "pull", [("assets/audio/s14_pig.mp3", "PIG", "I preheated the oven."),
                  ("assets/audio/s14_wolf.mp3", "WOLF", "A visionary.")]),
]


def cam_filter(cam):
    base = "scale=2160:3840:force_original_aspect_ratio=increase,crop=2160:3840"
    cx, cy = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    if cam == "push":          # slow push toward subject
        z, x, y = f"1+0.08*on/{N - 1}", cx, cy
    elif cam == "pull":        # gentle pull back
        z, x, y = f"1.08-0.08*on/{N - 1}", cx, cy
    elif cam == "pan":         # lateral move, left -> right
        z, x, y = "1.18", f"(iw-iw/zoom)*on/{N - 1}", cy
    elif cam == "pan_rev":     # lateral move, right -> left
        z, x, y = "1.18", f"(iw-iw/zoom)*(1-on/{N - 1})", cy
    else:                      # locked off (near-static)
        z, x, y = "1.02", cx, cy
    fade = f",fade=t=in:st=0:d=0.2,fade=t=out:st={DUR - 0.2}:d=0.2"
    return (f"{base},zoompan=z='{z}':x='{x}':y='{y}':d={N}:s={W}x{H}:fps={FPS}"
            f",format=yuv420p{fade}")


def stage_scenes():
    for n, cam, _ in SCENES:
        out = f"{WORK}/scene{n:02d}_v.mp4"
        if os.path.exists(out):
            print(f"skip {out}")
            continue
        run([FF, "-y", "-i", f"assets/scenes/scene{n:02d}.jpg",
             "-vf", cam_filter(cam), "-t", DUR,
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-r", FPS, out])


def line_timing(lines):
    """Return [(audio, speaker, text, start, end)] laid out from 0.5s."""
    durs = [duration(a) for a, _, _ in lines]
    gap = 0.35
    total = 0.5 + sum(durs) + gap * (len(lines) - 1)
    if total > DUR - 0.3:  # shrink gaps so dialogue fits the 8s scene
        gap = max(0.05, (DUR - 0.3 - 0.5 - sum(durs)) / max(1, len(lines) - 1))
    out, t = [], 0.5
    for (audio, speaker, text), d in zip(lines, durs):
        out.append((audio, speaker, text, t, t + d))
        t += d + gap
    return out


def split_sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def render_subtitle_png(text, path):
    font = ImageFont.truetype(FONT_PATH, 58)
    max_w = 940
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if font.getlength(trial) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    line_h = 74
    block_h = line_h * len(lines)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    widths = [font.getlength(l) for l in lines]
    box_w = max(widths) + 56
    box_h = block_h + 36
    x0 = (W - box_w) / 2
    y1 = 1720  # bottom of the subtitle block
    y0 = y1 - box_h
    draw.rounded_rectangle([x0, y0, x0 + box_w, y1], radius=18,
                           fill=(0, 0, 0, 150))
    y = y0 + 18
    for line, lw in zip(lines, widths):
        draw.text(((W - lw) / 2, y), line, font=font, fill=(255, 255, 255, 255),
                  stroke_width=2, stroke_fill=(0, 0, 0, 255))
        y += line_h
    img.save(path)


def stage_scenes_av():
    for n, _, lines in SCENES:
        timed = line_timing(lines)
        # --- dialogue mix ---
        inputs = [f"{WORK}/scene{n:02d}_v.mp4"] + [a for a, _, _, _, _ in timed]
        fc = []
        for i, (_, _, _, s, _) in enumerate(timed):
            ms = int(s * 1000)
            fc.append(f"[{i + 1}:a]adelay={ms}|{ms},aresample=44100[a{i}]")
        fc.append("".join(f"[a{i}]" for i in range(len(timed)))
                  + f"amix=inputs={len(timed)}:duration=longest,apad,"
                  + f"atrim=0:{DUR}[aout]")
        mixed = f"{WORK}/scene{n:02d}_av.mp4"
        run([FF, "-y", *sum([["-i", p] for p in inputs], []),
             "-filter_complex", ";".join(fc),
             "-map", "0:v", "-map", "[aout]",
             "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
             "-t", DUR, mixed])
        # --- subtitles ---
        subs = []  # (png, start, end)
        for audio, speaker, text, s, e in timed:
            sents = split_sentences(text)
            weights = [max(1, len(s)) for s in sents]
            span = e - s
            t = s
            for j, sent in enumerate(sents):
                dur_s = span * weights[j] / sum(weights)
                label = f"{speaker}: {sent}" if j == 0 else sent
                png = f"{WORK}/sub{n:02d}_{len(subs)}.png"
                render_subtitle_png(label, png)
                subs.append((png, t, t + dur_s))
                t += dur_s
        if not subs:
            run([FF, "-y", "-i", mixed, "-c", "copy",
                 f"{WORK}/scene{n:02d}_final.mp4"])
            continue
        cmd = [FF, "-y", "-i", mixed]
        for png, _, _ in subs:
            cmd += ["-i", png]
        fc = []
        prev = "[0:v]"
        for i, (_, s, e) in enumerate(subs):
            out = f"[v{i}]"
            fc.append(f"{prev}[{i + 1}:v]overlay=0:0:"
                      f"enable='between(t,{s:.2f},{e:.2f})'{out}")
            prev = out
        run(cmd + ["-filter_complex", ";".join(fc),
                   "-map", prev, "-map", "0:a",
                   "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                   "-c:a", "copy", f"{WORK}/scene{n:02d}_final.mp4"])


def stage_final():
    lst = f"{WORK}/concat.txt"
    with open(lst, "w") as f:
        for n, _, _ in SCENES:
            f.write(f"file '{os.path.abspath(f'{WORK}/scene{n:02d}_final.mp4')}'\n")
    run([FF, "-y", "-f", "concat", "-safe", "0", "-i", lst,
         "-c", "copy", f"{WORK}/concat.mp4"])
    total = DUR * len(SCENES)
    run([FF, "-y", "-i", f"{WORK}/concat.mp4",
         "-stream_loop", "-1", "-i", BGM,
         "-filter_complex",
         f"[1:a]atrim=0:{total},volume=0.10,afade=t=in:st=0:d=1,"
         f"afade=t=out:st={total - 4}:d=4[bgm];"
         f"[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=0[a]",
         "-map", "0:v", "-map", "[a]",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
         "-t", total, "output/golden-peep-visionary.mp4"])


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "all"
    if stage in ("scenes", "all"):
        stage_scenes()
    if stage in ("scenes-av", "all"):
        stage_scenes_av()
    if stage in ("final", "all"):
        stage_final()
    print("done:", stage)
