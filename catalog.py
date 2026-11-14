import json, os, subprocess, sys, time, urllib.parse, urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

LIB = Path("library")
N = 5  # عدد الصور المرشّحة لكل مفهوم

# المفهوم: (كلمات البحث, النوع, كلمات يجب أن تظهر في وسوم الصورة, الوصف بالعربية)
CONCEPTS = {
    "kidney_anatomy": ("kidney anatomy", "illustration", ["kidney"], "رسم تشريحي للكلى"),
    "kidney_health": ("healthy kidneys illustration", "illustration", ["kidney"], "الكلى (رسم توضيحي)"),
    "dialysis_machine": ("dialysis machine", "photo", ["dialysis"], "جهاز غسيل الكلى"),
    "water_glass": ("glass of water", "photo", ["water", "glass"], "كوب ماء"),
    "water_bottle": ("drinking water bottle", "photo", ["water", "bottle"], "شرب الماء"),
    "dehydration": ("dehydration thirst", "photo", ["dehydration", "thirst", "thirsty"], "الجفاف والعطش"),
    "doctor_patient": ("doctor talking to patient", "photo", ["doctor", "patient"], "طبيب مع مريض"),
    "doctor_elderly": ("doctor elderly patient", "photo", ["elderly", "senior", "old"], "طبيب مع مريض كبير السن"),
    "stethoscope": ("stethoscope", "photo", ["stethoscope"], "سماعة طبية"),
    "nurse": ("nurse caring patient", "photo", ["nurse"], "ممرضة ترعى مريضاً"),
    "hospital": ("hospital corridor", "photo", ["hospital"], "مستشفى"),
    "blood_test": ("blood test laboratory", "photo", ["blood", "laboratory", "lab"], "تحليل دم"),
    "blood_pressure": ("blood pressure measurement", "photo", ["blood", "pressure"], "قياس ضغط الدم"),
    "glucose_meter": ("blood sugar glucose meter", "photo", ["glucose", "diabetes", "sugar"], "قياس السكر"),
    "pills": ("medication pills", "photo", ["pill", "medicine", "medication", "tablet"], "أدوية"),
    "pill_organizer": ("pill organizer weekly", "photo", ["pill", "organizer", "medication"], "منظّم الأدوية"),
    "painkillers": ("painkiller tablets", "photo", ["painkiller", "pain", "tablet"], "مسكنات الألم"),
    "salt": ("salt shaker", "photo", ["salt"], "الملح"),
    "sugar": ("sugar cubes spoon", "photo", ["sugar"], "السكر"),
    "vegetables": ("fresh vegetables", "photo", ["vegetable"], "خضروات طازجة"),
    "fruits": ("fresh fruit basket", "photo", ["fruit"], "فواكه"),
    "healthy_meal": ("healthy meal plate", "photo", ["meal", "plate", "healthy"], "وجبة صحية"),
    "cooking_home": ("cooking at home kitchen", "photo", ["cooking", "kitchen"], "طبخ منزلي"),
    "fish": ("grilled fish dinner", "photo", ["fish"], "سمك مشوي"),
    "eggs": ("boiled eggs", "photo", ["egg"], "بيض"),
    "fast_food": ("fast food burger fries", "photo", ["fast", "burger", "fries"], "وجبات سريعة"),
    "soda": ("soda soft drink cola", "photo", ["soda", "cola", "drink"], "مشروبات غازية"),
    "processed_snacks": ("chips snacks processed food", "photo", ["chips", "snack", "processed"], "وجبات خفيفة معلّبة"),
    "smoking": ("cigarette smoking", "photo", ["cigarette", "smoking"], "التدخين"),
    "walking": ("walking exercise outdoors", "photo", ["walking", "walk", "exercise"], "المشي"),
    "sleep": ("sleeping well bed", "photo", ["sleep", "bed"], "النوم"),
    "food_label": ("reading food label nutrition", "photo", ["label", "nutrition"], "قراءة ملصق الغذاء"),
    "appointment": ("medical appointment calendar", "photo", ["calendar", "appointment"], "موعد طبي"),
    "family_support": ("family supporting elderly", "photo", ["family", "support", "elderly"], "دعم الأسرة"),
    "herbal_tea": ("herbal tea cup", "photo", ["tea", "herbal"], "شاي أعشاب"),
}

KEY = os.environ.get("PIXABAY_API_KEY", "").strip()
TG_TOKEN = os.environ.get("TG_TOKEN", "").strip()
TG_CHAT = os.environ.get("TG_CHAT", "").strip()
UA = {"User-Agent": "Mozilla/5.0"}


def stem(w):
    w = w.lower()
    return w[:-1] if w.endswith("s") and len(w) > 3 else w


def get_json(url):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30))


def candidates(query, kind, must):
    words = [stem(w) for w in must]
    out, seen = [], set()
    for orient in ("vertical", "all"):
        url = "https://pixabay.com/api/?" + urllib.parse.urlencode(
            {"key": KEY, "q": query, "image_type": kind, "orientation": orient,
             "safesearch": "true", "per_page": 40})
        for h in get_json(url).get("hits", []):
            tags = h.get("tags", "").lower()
            if h["id"] in seen or not any(w in tags for w in words):
                continue
            seen.add(h["id"])
            out.append(h)
        if len(out) >= N:
            break
    return out[:N]


def download(url, path):
    data = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()
    path.write_bytes(data)
    img = Image.open(path).convert("RGB")
    img.thumbnail((1600, 1600))
    img.save(path, quality=85)
    return img


def cover(img, w, h):
    s = max(w / img.width, h / img.height)
    img = img.resize((int(img.width * s) + 1, int(img.height * s) + 1))
    l, t = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((l, t, l + w, t + h))


def sheet(key, imgs, path):
    tw, th, gap = 300, 450, 10
    sh = Image.new("RGB", (len(imgs) * (tw + gap) + gap, th + 2 * gap), (255, 255, 255))
    f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 70)
    d = ImageDraw.Draw(sh)
    for i, im in enumerate(imgs, 1):
        x = gap + (i - 1) * (tw + gap)
        sh.paste(cover(im, tw, th), (x, gap))
        d.ellipse((x + 10, gap + 10, x + 100, gap + 100), fill=(200, 0, 0))
        d.text((x + 55, gap + 55), str(i), font=f, fill=(255, 255, 255), anchor="mm")
    sh.save(path, quality=88)


def send(path, caption):
    if not (TG_TOKEN and TG_CHAT):
        return
    subprocess.run(["curl", "-sS", "-f", "-X", "POST", f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto",
                    "-F", f"chat_id={TG_CHAT}", "-F", f"photo=@{path}", "-F", f"caption={caption}"], check=False)
    time.sleep(1.2)


def main():
    LIB.mkdir(exist_ok=True)
    only = [k for k in os.environ.get("ONLY", "").split(",") if k.strip()]
    for key, (query, kind, must, ar) in CONCEPTS.items():
        if only and key not in only:
            continue
        try:
            hits = candidates(query, kind, must)
        except Exception as e:
            print("FAILED", key, e)
            continue
        d = LIB / key
        d.mkdir(exist_ok=True)
        imgs = []
        for i, h in enumerate(hits, 1):
            try:
                imgs.append(download(h.get("largeImageURL") or h.get("webformatURL"), d / f"{i}.jpg"))
            except Exception as e:
                print("download failed", key, i, e)
        print(key, len(imgs), "images")
        if imgs:
            p = Path("sheet.jpg")
            sheet(key, imgs, p)
            send(p, f"{key}\n{ar}\nاختر حتى 3 أرقام مناسبة (مثل 1,3,4) من 1 إلى {len(imgs)}، أو 0 إن لم تناسب أي صورة")


main()
