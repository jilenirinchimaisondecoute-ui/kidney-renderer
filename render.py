import asyncio, json, os, subprocess, sys
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, features

W, H = 1080, 1920
OUT = Path("out")
TARGET = 45.0          # مدة الصوت المستهدفة بالثواني
MIN_OK, MAX_OK = 40.0, 50.0
PALETTES = [((8, 60, 90), (20, 130, 160)), ((20, 70, 80), (60, 160, 150)), ((15, 45, 95), (70, 120, 190))]

HAS_RAQM = features.check("raqm")
if not HAS_RAQM:  # بديل عند غياب raqm
    import arabic_reshaper
    from bidi.algorithm import get_display


def find_font():
    for fam in ("Amiri", "Noto Naskh Arabic", "DejaVu Sans"):
        try:
            out = subprocess.check_output(["fc-match", "-f", "%{family}|%{file}", f"{fam}:bold"], text=True)
            family, path = out.split("|", 1)
            if fam.lower() in family.lower() and path:
                return path
        except Exception:
            pass
    return "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


FONT = find_font()


def font(size):
    eng = ImageFont.Layout.RAQM if HAS_RAQM else ImageFont.Layout.BASIC
    return ImageFont.truetype(FONT, size, layout_engine=eng)


def shape(text):
    return text if HAS_RAQM else get_display(arabic_reshaper.reshape(text))


def kw():
    return {"direction": "rtl", "language": "ar"} if HAS_RAQM else {}


def tlen(d, text, f):
    return d.textlength(shape(text), font=f, **kw())


def wrap(d, text, f, max_w):
    lines, cur = [], ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if tlen(d, trial, f) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def make_background(idx, photo_path, path):
    """خلفية 1296x2304 (أكبر من الإطار لتأثير التقريب)."""
    bw, bh = 1296, 2304
    if photo_path:
        img = Image.open(photo_path).convert("RGB")
        s = max(bw / img.width, bh / img.height)
        img = img.resize((int(img.width * s) + 1, int(img.height * s) + 1))
        l, t = (img.width - bw) // 2, (img.height - bh) // 2
        img = img.crop((l, t, l + bw, t + bh))
        dark = Image.new("RGB", (bw, bh), (5, 25, 45))
        img = Image.blend(img, dark, 0.45)
    else:
        c1, c2 = PALETTES[idx % len(PALETTES)]
        img = Image.new("RGB", (bw, bh), c1)
        d = ImageDraw.Draw(img)
        for y in range(bh):
            t = y / bh
            d.line([(0, y), (bw, y)], fill=tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3)))
    img.save(path, quality=92)


def make_text_layer(text, title, path):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # العنوان في الأعلى داخل شريط
    tf = font(52)
    tl = wrap(d, title, tf, W - 200)
    th = len(tl) * 76 + 40
    d.rounded_rectangle((60, 90, W - 60, 90 + th), 36, fill=(0, 40, 70, 190))
    for k, line in enumerate(tl):
        d.text((W / 2, 90 + 20 + 38 + k * 76), shape(line), font=tf, fill=(210, 240, 245, 255), anchor="mm", **kw())
    # نص المشهد في الوسط السفلي داخل لوح شبه شفاف
    bf = font(78)
    lines = wrap(d, text, bf, W - 220)
    lh = 128
    bh = len(lines) * lh + 70
    y0 = int(H * 0.60)
    d.rounded_rectangle((70, y0, W - 70, y0 + bh), 44, fill=(0, 0, 0, 165))
    for k, line in enumerate(lines):
        d.text((W / 2, y0 + 35 + lh / 2 + k * lh), shape(line), font=bf, fill=(255, 255, 255, 255), anchor="mm", **kw())
    img.save(path)


LIB = Path("library")
try:
    APPROVED = json.load(open("approved.json", encoding="utf-8"))
except Exception:
    APPROVED = {}
USED_IMAGES = set()  # لمنع تكرار الصورة نفسها داخل الفيديو الواحد


def pick_image(concept, scene_idx, video_idx):
    """يختار صورة معتمدة فقط من المكتبة، بالتدوير حسب اليوم ورقم الفيديو. وإلا لا صورة (بطاقة نصية)."""
    slots = APPROVED.get(concept) or []
    paths = [LIB / concept / f"{n}.jpg" for n in slots if (LIB / concept / f"{n}.jpg").exists()]
    if not paths:
        print("no approved image for concept:", repr(concept), "-> plain card")
        return None
    start = date.today().toordinal() + 7 * int(video_idx) + scene_idx
    for k in range(len(paths)):
        p = paths[(start + k) % len(paths)]
        if p not in USED_IMAGES:
            USED_IMAGES.add(p)
            print("image:", p)
            return p
    p = paths[start % len(paths)]  # كل الصور المعتمدة استُخدمت في هذا الفيديو
    print("image (reused):", p)
    return p


def duration(path):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], text=True)
    return float(out.strip())


async def synth(text, voice, rate_pct, path):
    import edge_tts
    await edge_tts.Communicate(text, voice, rate=f"{rate_pct:+d}%").save(str(path))


async def make_voice(job, mp3):
    voice = job.get("voice") or "ar-AE-HamdanNeural"  # صوت رجالي
    rate = -5
    await synth(job["script"], voice, rate, mp3)
    d = duration(mp3)
    if d < MIN_OK or d > MAX_OK:  # تعديل سرعة النطق ليقترب من 45 ثانية
        new = (1 + rate / 100) * d / TARGET - 1
        rate = max(-30, min(30, round(new * 100)))
        await synth(job["script"], voice, rate, mp3)
        d = duration(mp3)
    return d, rate


def build_video(job, mp3, total):
    scenes = job["scenes"]
    weights = [max(float(s.get("seconds", 6)), 1) for s in scenes]
    scale = (total + 0.4) / sum(weights)
    clips = []
    for i, s in enumerate(scenes):
        photo = pick_image(s.get("concept", ""), i, (job.get("meta") or {}).get("idx", 0))
        bg, tx, clip = OUT / f"bg{i}.jpg", OUT / f"tx{i}.png", OUT / f"clip{i}.mp4"
        make_background(i, photo, bg)
        make_text_layer(s["text"], job["title"], tx)
        dur = weights[i] * scale
        frames = max(int(round(dur * 30)), 30)
        fc = (f"[0:v]zoompan=z='min(1+0.0007*on,1.18)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
              f":d={frames}:s={W}x{H}:fps=30[b];[b][1:v]overlay=0:0,format=yuv420p[v]")
        subprocess.run(["ffmpeg", "-y", "-i", str(bg), "-i", str(tx), "-filter_complex", fc, "-map", "[v]",
                        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", str(clip)],
                       check=True, capture_output=True)
        clips.append(clip)
    lst = OUT / "clips.txt"
    lst.write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(mp3),
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart",
                    str(OUT / "video.mp4")], check=True, capture_output=True)


async def main(job_file):
    job = json.load(open(job_file, encoding="utf-8"))
    OUT.mkdir(exist_ok=True)
    mp3 = OUT / "voice.mp3"
    total, rate = await make_voice(job, mp3)
    build_video(job, mp3, total)
    res = {"duration": round(total, 1), "in_range": MIN_OK <= total <= MAX_OK, "rate": rate}
    (OUT / "result.json").write_text(json.dumps(res))
    print(res)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
