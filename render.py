import asyncio, json, os, subprocess, sys
from pathlib import Path

import edge_tts
import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
PALETTES = [((8, 60, 90), (20, 130, 160)), ((20, 70, 80), (60, 160, 150)), ((15, 45, 95), (70, 120, 190))]
OUT = Path("out")


def find_font():
    try:
        p = subprocess.check_output(["fc-match", "-f", "%{file}", "Amiri:bold"], text=True)
        if p:
            return p
    except Exception:
        pass
    return "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


FONT = find_font()


def ar(text):
    return get_display(arabic_reshaper.reshape(text))


def wrap(draw, text, font, max_w):
    lines, cur = [], ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if draw.textlength(ar(trial), font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def make_frame(text, title, idx, path):
    c1, c2 = PALETTES[idx % len(PALETTES)]
    img = Image.new("RGB", (W, H), c1)
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3)))
    tf = ImageFont.truetype(FONT, 54)
    for k, line in enumerate(wrap(d, title, tf, W - 160)):
        d.text((W / 2, 170 + k * 80), ar(line), font=tf, fill=(200, 235, 240), anchor="mm")
    bf = ImageFont.truetype(FONT, 82)
    lines = wrap(d, text, bf, W - 180)
    y0 = H / 2 - len(lines) * 70
    for k, line in enumerate(lines):
        d.text((W / 2, y0 + k * 140), ar(line), font=bf, fill="white", anchor="mm")
    img.save(path)


def audio_duration(path):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], text=True)
    return float(out.strip())


async def main(job_file):
    job = json.load(open(job_file, encoding="utf-8"))
    OUT.mkdir(exist_ok=True)
    mp3 = OUT / "voice.mp3"
    voice = job.get("voice") or "ar-LY-ImanNeural"
    await edge_tts.Communicate(job["script"], voice, rate="-5%").save(str(mp3))
    total = audio_duration(mp3)

    scenes = job["scenes"]
    weights = [max(float(s.get("seconds", 8)), 1) for s in scenes]
    scale = (total + 0.4) / sum(weights)
    lst = OUT / "list.txt"
    last = None
    with open(lst, "w") as f:
        for i, s in enumerate(scenes):
            p = (OUT / f"f{i}.png").resolve()
            make_frame(s["text"], job["title"], i, p)
            f.write(f"file '{p}'\nduration {weights[i] * scale:.3f}\n")
            last = p
        f.write(f"file '{last}'\n")

    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(mp3),
           "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
           "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", str(OUT / "video.mp4")]
    subprocess.run(cmd, check=True)
    print(f"duration={total:.1f}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
