"""خط الإنتاج اليومي: أفكار (Gemini) -> فيديوهات -> تيليغرام، ومعالجة ردود ok / No."""
import json, os, re, subprocess, sys, time, traceback, urllib.error, urllib.request
from datetime import datetime, timedelta
from pathlib import Path

STATE = Path("state")
JOBS = STATE / "jobs"
HISTORY = STATE / "history.json"
OUT = Path("out")

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
TG_TOKEN = os.environ.get("TG_TOKEN", "")
TG_CHAT = os.environ.get("TG_CHAT", "")

MODELS = ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
TIMES = ["08:00", "12:00", "18:00"]  # توقيت ليبيا
CATEGORIES = [
    ("explain_aki", "شرح الفشل الكلوي الحاد: أسبابه وعلاماته ومتى يُراجَع الطبيب"),
    ("explain_ckd", "شرح مرض الكلى المزمن: ما هو وكيف يتطور ولماذا المتابعة مهمة"),
    ("patient_advice", "نصيحة عملية لمريض الكلى في حياته اليومية"),
    ("meal_idea", "فكرة وجبة أو مكوّنات مناسبة عموماً لمرضى الكلى (دون كميات أو أرقام)"),
    ("bad_habit", "عادة سيئة يجب تجنبها لأنها تضر الكلى"),
    ("good_habit", "عادة جيدة تحمي الكلى وتفيد المريض"),
]
CONCEPT_AR = {
    "kidney_anatomy": "رسم/تشريح الكلية", "kidney_health": "صحة الكلى بشكل عام", "water_glass": "كأس ماء",
    "water_bottle": "قارورة ماء", "dehydration": "الجفاف", "doctor_patient": "طبيب مع مريض",
    "doctor_elderly": "طبيب مع مريض مسن", "stethoscope": "سماعة طبية", "nurse": "ممرضة", "hospital": "مستشفى",
    "blood_test": "تحليل دم", "blood_pressure": "قياس ضغط الدم", "glucose_meter": "جهاز قياس السكر",
    "pills": "أدوية وحبوب", "pill_organizer": "منظم أدوية", "painkillers": "مسكنات ألم", "salt": "ملح",
    "sugar": "سكر", "vegetables": "خضروات", "fruits": "فواكه", "healthy_meal": "وجبة صحية",
    "cooking_home": "طبخ منزلي", "fish": "سمك", "eggs": "بيض", "fast_food": "وجبات سريعة",
    "soda": "مشروبات غازية", "processed_snacks": "وجبات خفيفة مصنعة", "smoking": "تدخين",
    "walking": "مشي ورياضة خفيفة", "appointment": "موعد ومتابعة طبية", "family_support": "دعم الأسرة",
    "herbal_tea": "شاي أعشاب",
}
DISCLAIMER = {
    "text": "معلومات عامة وليست بديلاً عن استشارة الطبيب",
    "narration": "هذه معلومات عامة وليست بديلاً عن استشارة الطبيب.",
    "concept": "doctor_patient",
}
BAD_PATTERNS = [
    r"[0-9٠-٩]+\s*(mg|ml|g|kg|ملغ|ملغم|ميلغرام|مل|ملل|غرام|جرام|كغ|لتر|كوب|أكواب|كأس|كؤوس)",
    r"جرعة|جرعات|ميلغرام|ملغ",
]
SOURCES_HINT = "منظمة الصحة العالمية (WHO)، NIDDK/NIH، المؤسسة الوطنية للكلى (NKF)، KDIGO، Mayo Clinic، CDC، NHS، American Kidney Fund، الجمعية الدولية لأمراض الكلى (ISN)"


# ----------------------------------------------------------------- أدوات عامة
def libya_today():
    return (datetime.utcnow() + timedelta(hours=2)).date()


def load_json(path, default):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


def save_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def words(text):
    return len(re.findall(r"\S+", text))


# ----------------------------------------------------------------- تيليغرام
def tg_call(method, fields, timeout=300):
    cmd = ["curl", "-sS", "-X", "POST", f"https://api.telegram.org/bot{TG_TOKEN}/{method}", "--max-time", str(timeout)]
    for k, v in fields.items():
        cmd += ["-F", f"{k}={v}"]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    try:
        res = json.loads(out)
    except Exception:
        raise RuntimeError(f"telegram {method}: bad response {out[:200]}")
    if not res.get("ok"):
        raise RuntimeError(f"telegram {method}: {res.get('description')}")
    return res["result"]


def tg_text(text):
    try:
        tg_call("sendMessage", {"chat_id": TG_CHAT, "text": text[:3900]})
    except Exception as e:
        print("tg_text failed:", e)


def tg_video(video, caption):
    """video: مسار ملف (@path) أو file_id. يرجع file_id."""
    v = f"@{video}" if os.path.exists(str(video)) else video
    res = tg_call("sendVideo", {"chat_id": TG_CHAT, "video": v, "caption": caption[:1000],
                                "supports_streaming": "true"})
    return res["video"]["file_id"]


# ----------------------------------------------------------------- Gemini
def gemini(prompt, search=False, json_mode=False, temperature=0.8):
    """يرجع (نص، قائمة مصادر). يجرب النماذج بالترتيب ويعيد المحاولة عند الازدحام."""
    errors = []
    for model in MODELS:
        for attempt in range(3):
            body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": temperature}}
            if search:
                body["tools"] = [{"google_search": {}}]
            if json_mode:
                body["generationConfig"]["responseMimeType"] = "application/json"
            req = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                data=json.dumps(body).encode(), method="POST",
                headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_KEY})
            try:
                with urllib.request.urlopen(req, timeout=180) as r:
                    data = json.load(r)
                cand = (data.get("candidates") or [{}])[0]
                text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []))
                chunks = (cand.get("groundingMetadata") or {}).get("groundingChunks") or []
                srcs = []
                for c in chunks:
                    t = (c.get("web") or {}).get("title")
                    if t and t not in srcs:
                        srcs.append(t)
                if text.strip():
                    print(f"gemini ok: {model} search={search} chars={len(text)} sources={len(srcs)}")
                    return text, srcs
                errors.append(f"{model}: empty")
            except urllib.error.HTTPError as e:
                msg = e.read().decode(errors="ignore")
                print(f"gemini error: {model}: HTTP {e.code} {msg[:400]}")
                m2 = re.search(r'"message":\s*"([^"]{0,120})', msg)
                errors.append(f"{model}: HTTP {e.code} {m2.group(1) if m2 else ''}")
                if e.code in (429, 500, 503):
                    time.sleep(8 * (attempt + 1))
                    continue
                break  # 400/403/404: جرّب النموذج التالي
            except Exception as e:
                errors.append(f"{model}: {str(e)[:80]}")
                time.sleep(5)
    raise RuntimeError("gemini failed -> " + " | ".join(errors[-6:]))


def parse_json(text):
    t = text.strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.M).strip()
    a, b = t.find("{"), t.rfind("}")
    return json.loads(t[a:b + 1])


# ----------------------------------------------------------------- التحقق من المحتوى
def norm_tokens(s):
    return set(re.findall(r"[\u0600-\u06FFa-zA-Z]{3,}", s))


def too_similar(title, recent_titles):
    a = norm_tokens(title)
    for t in recent_titles:
        b = norm_tokens(t)
        if a and b and len(a & b) / len(a | b) >= 0.6:
            return t
    return None


def validate(idea, allowed, recent_titles):
    probs = []
    scenes = idea.get("scenes") or []
    if not (5 <= len(scenes) <= 7):
        probs.append(f"عدد المشاهد {len(scenes)} (المطلوب 5 إلى 7)")
    total = 0
    for s in scenes:
        if not (s.get("text") or "").strip() or not (s.get("narration") or "").strip():
            probs.append("مشهد بلا text أو narration")
            continue
        total += words(s["narration"])
        if words(s["text"]) > 9:
            probs.append("نص الشاشة أطول من 9 كلمات")
        if s.get("concept") and s["concept"] not in allowed:
            s["concept"] = ""  # مفهوم غير معتمد -> بطاقة نصية آمنة
    if not (60 <= total <= 85):
        probs.append(f"عدد كلمات السرد {total} (المطلوب 60 إلى 85)")
    full = " ".join((s.get("narration") or "") + " " + (s.get("text") or "") for s in scenes) + " " + (idea.get("title") or "")
    for p in BAD_PATTERNS:
        if re.search(p, full, flags=re.I):
            probs.append("ذكر جرعات أو كميات رقمية (ممنوع)")
            break
    if not (idea.get("title") or "").strip() or len(idea["title"]) > 90:
        probs.append("العنوان مفقود أو طويل")
    dup = too_similar(idea.get("title", ""), recent_titles)
    if dup:
        probs.append(f"العنوان يشبه فكرة سابقة: {dup}")
    return probs


def finalize_scenes(scenes):
    """يضيف مشهد إخلاء المسؤولية الثابت في آخر المحتوى (الخاتمة تضيفها render.py)."""
    out = [{"text": s["text"].strip(), "narration": s["narration"].strip(), "concept": s.get("concept", "") or ""}
           for s in scenes]
    out.append(dict(DISCLAIMER))
    return out


# ----------------------------------------------------------------- توليد الأفكار
def allowed_concepts():
    approved = load_json("approved.json", {})
    return {k: v for k, v in CONCEPT_AR.items() if approved.get(k)}


def concepts_help(allowed):
    return "\n".join(f"- {k}: {v}" for k, v in allowed.items())


def generate_ideas(n, today, history):
    recent = [h.get("title", "") for h in history[-150:]]
    recent_topics = [h.get("topic", "") for h in history[-150:] if h.get("topic")]
    base = today.toordinal() * 3
    cats = [CATEGORIES[(base + i) % len(CATEGORIES)] for i in range(n)]
    cats_txt = "\n".join(f"{i + 1}) {c[0]}: {c[1]}" for i, c in enumerate(cats))
    avoid = "\n".join(f"- {t}" for t in (recent + recent_topics)[-120:]) or "(لا شيء بعد)"

    research_prompt = (
        "أنت محرر صحي متخصص في أمراض الكلى. ابحث على الإنترنت في مصادر موثوقة فقط "
        f"({SOURCES_HINT}) لإعداد {n} مواضيع توعوية جديدة لمرضى الكلى، واحد لكل فئة:\n{cats_txt}\n\n"
        f"لا تكرر أي موضوع من هذه القائمة السابقة:\n{avoid}\n\n"
        "لكل موضوع اكتب: اسم الموضوع، ثم 4 إلى 6 حقائق مؤكدة مختصرة وآمنة للعموم، ثم اسم المصدر الذي اعتمدت عليه. "
        "ممنوع ذكر جرعات أدوية أو كميات رقمية للسوائل أو الأملاح أو البروتين. اكتب بالعربية الفصحى المبسطة.")
    try:
        notes, srcs = gemini(research_prompt, search=True)
    except Exception as e:  # بدون بحث (قد لا يتوفر في الحصة المجانية)
        print("search grounding unavailable:", e)
        tg_text("ℹ️ ميزة البحث في الإنترنت لم تتوفر اليوم، فاعتمد النموذج على معرفته. راجع المحتوى بعناية.\nالسبب: " + str(e)[:500])
        notes, srcs = gemini(research_prompt.replace("ابحث على الإنترنت في", "اعتمد على معرفتك الموثوقة بـ"), search=False)

    write_prompt = f"""أنت كاتب سيناريوهات فيديوهات قصيرة (تيك توك) عن صحة الكلى للمرضى، بالعربية الفصحى المبسطة (لغة بيضاء واضحة، بلا لهجات).
اعتمد فقط على الملاحظات التالية ولا تضف معلومة غير موجودة فيها:
-----
{notes}
-----
اكتب {n} فيديوهات، واحد لكل فئة بالترتيب: {", ".join(c[0] for c in cats)}.

قواعد صارمة:
- كل فيديو من 5 إلى 7 مشاهد، ومجموع كلمات حقول narration لكل فيديو بين 65 و80 كلمة.
- narration: الجملة التي ينطقها المعلق بالضبط في هذا المشهد (جمل قصيرة، تُنطق في 6 إلى 12 ثانية). يبدأ الفيديو بجملة جذب تثير الانتباه.
- text: عبارة قصيرة تظهر على الشاشة (لا تزيد عن 7 كلمات) تلخص المشهد.
- concept: مفتاح صورة من القائمة أدناه، ويجب أن تصوّر الصورة المعنى المنطوق في المشهد حرفياً. إن لم تتوفر صورة مطابقة تماماً فاكتب "" (فارغ). لا تختر صورة تقريبية أبداً.
- ممنوع ذكر جرعات أدوية أو كميات رقمية (ملغ، مل، غرام، أكواب...). ممنوع وعود العلاج أو الشفاء. أي نصيحة غذائية تُختم بأن الكمية والنوع يحددهما الطبيب أو أخصائي التغذية.
- لا تنصح بالأعشاب أو المكملات. إن ذُكرت فللتحذير منها دون إشراف الطبيب.
- لا تكتب جملة «هذه معلومات عامة...» ولا جملة المشاركة، فهما تُضافان تلقائياً.
- title: عنوان جذاب لا يتجاوز 70 حرفاً. caption: وصف للمنشور في جملتين. hashtags: 5 وسوم تبدأ بـ # (عربية وإنجليزية).
- topic: اسم الموضوع في 3 إلى 6 كلمات (لمنع التكرار لاحقاً).
- يجب أن تختلف العناوين عن هذه السابقة:
{avoid}

مفاتيح الصور المتاحة (concept):
{concepts_help(allowed_concepts())}

أخرج JSON فقط بهذا الشكل:
{{"ideas":[{{"category":"","topic":"","title":"","caption":"","hashtags":"","scenes":[{{"text":"","narration":"","concept":""}}]}}]}}"""
    allowed = allowed_concepts()
    good, tries, feedback = [], 0, ""
    while len(good) < n and tries < 3:
        tries += 1
        text, _ = gemini(write_prompt + feedback, json_mode=True, temperature=0.7)
        try:
            ideas = parse_json(text).get("ideas", [])
        except Exception as e:
            feedback = f"\n\nالمحاولة السابقة لم تكن JSON صالحاً ({e}). أعد الإخراج بشكل صحيح."
            continue
        problems = []
        for idea in ideas:
            probs = validate(idea, allowed, recent + [g["title"] for g in good])
            if probs:
                problems.append(f"«{idea.get('title', '?')}»: " + "؛ ".join(probs))
            elif len(good) < n:
                idea["sources"] = srcs
                good.append(idea)
        if len(good) < n:
            feedback = "\n\nأخطاء المحاولة السابقة، أصلحها واكتب الأفكار كلها من جديد:\n" + "\n".join(problems)
    return good


# ----------------------------------------------------------------- الصناعة والإرسال
def render_job(job):
    """يصنع الفيديو ويرجع (مسار الملف، المدة)."""
    OUT.mkdir(exist_ok=True)
    job_file = OUT / "job.json"
    save_json(job_file, {
        "title": job["title"], "voice": "ar-AE-HamdanNeural", "script": " ".join(s["narration"] for s in job["scenes"]),
        "scenes": job["scenes"], "meta": {"idx": job["idx"]}, "variant": job.get("version", 1) - 1})
    for f in ("video.mp4", "result.json"):
        (OUT / f).unlink(missing_ok=True)
    subprocess.run([sys.executable, "render.py", str(job_file)], check=True)
    res = load_json(OUT / "result.json", {})
    target = OUT / f"{job['id']}-v{job.get('version', 1)}.mp4"
    (OUT / "video.mp4").replace(target)
    return target, res.get("duration", 0)


def caption_for(job, dur):
    v = job.get("version", 1)
    warn = "" if 40 <= dur <= 52 else "\n⚠️ المدة خارج النطاق المطلوب"
    srcs = "، ".join(job.get("sources", [])[:4])
    return (f"🎬 {job['title']}\n\n{job.get('caption', '')}\n\n{job.get('hashtags', '')}\n\n"
            f"⏰ وقت النشر المقترح: {job.get('publish_time', '')}\n⏱ المدة: {dur:.1f} ث{warn}\n"
            + (f"📚 المصادر: {srcs}\n" if srcs else "")
            + f"🆔 {job['id']} (النسخة {v})\n\n"
            "للموافقة والنشر: اكتب ok بالرد (Reply) على هذه الرسالة\n"
            "للرفض: اكتب No ثم سبب الرفض (اختياري) بالرد على هذه الرسالة")


def produce(job):
    path, dur = render_job(job)
    fid = tg_video(str(path), caption_for(job, dur))
    job["file_id"] = fid
    job["duration"] = dur
    save_json(JOBS / f"{job['id']}.json", job)


def run_daily():
    today = libya_today()
    history = load_json(HISTORY, [])
    ideas = generate_ideas(3, today, history)
    if not ideas:
        tg_text("⚠️ تعذّر توليد أفكار صالحة اليوم بعد عدة محاولات. سأحاول غداً تلقائياً، أو شغّل المهمة يدوياً من GitHub.")
        raise SystemExit(1)
    if len(ideas) < 3:
        tg_text(f"ℹ️ تم توليد {len(ideas)} من 3 أفكار فقط اليوم (البقية لم تجتز فحص الجودة).")
    for i, idea in enumerate(ideas):
        job = {
            "id": f"{today:%Y%m%d}-{i + 1}", "date": str(today), "idx": i + 1, "version": 1,
            "category": idea.get("category", ""), "topic": idea.get("topic", ""), "title": idea["title"].strip(),
            "caption": idea.get("caption", "").strip(), "hashtags": idea.get("hashtags", "").strip(),
            "publish_time": TIMES[i % 3], "sources": idea.get("sources", []),
            "scenes": finalize_scenes(idea["scenes"]), "status": "pending", "feedback": [],
        }
        history.append({"id": job["id"], "date": job["date"], "title": job["title"], "topic": job["topic"],
                        "category": job["category"], "status": "pending"})
        save_json(HISTORY, history)  # نحفظ فوراً كي لا يضيع شيء إن فشل فيديو لاحق
        try:
            produce(job)
        except Exception as e:
            traceback.print_exc()
            tg_text(f"⚠️ فشلت صناعة فيديو «{job['title']}»: {str(e)[:300]}")
            save_json(JOBS / f"{job['id']}.json", job)


# ----------------------------------------------------------------- الردود
def revise(job, feedback):
    allowed = allowed_concepts()
    cur = [{"text": s["text"], "narration": s["narration"], "concept": s["concept"]}
           for s in job["scenes"] if s["narration"] != DISCLAIMER["narration"]]
    prompt = f"""هذا سيناريو فيديو صحي عن الكلى بالعربية الفصحى المبسطة رفضه المشرف.
العنوان: {job['title']}
المشاهد الحالية (JSON): {json.dumps(cur, ensure_ascii=False)}
ملاحظات المشرف: {feedback or '(لم يذكر سبباً: حسّن الصياغة واجعل الصور أدق مطابقة للكلام)'}

أعد كتابة المشاهد لإصلاح الملاحظات مع الالتزام بالقواعد: 5 إلى 7 مشاهد، مجموع كلمات narration بين 65 و80،
text لا يزيد عن 7 كلمات، concept من القائمة فقط ويجب أن تصوّر المعنى المنطوق حرفياً وإلا فاتركه "" ،
ممنوع الجرعات والكميات الرقمية ووعود الشفاء، ولا تكتب جملة إخلاء المسؤولية ولا جملة المشاركة.
مفاتيح الصور:
{concepts_help(allowed)}
أخرج JSON فقط: {{"scenes":[{{"text":"","narration":"","concept":""}}]}}"""
    for _ in range(2):
        try:
            text, _ = gemini(prompt, json_mode=True, temperature=0.6)
            scenes = parse_json(text).get("scenes", [])
            probs = validate({"scenes": scenes, "title": job["title"]}, allowed, [])
            if not probs:
                return finalize_scenes(scenes)
            prompt += "\n\nأخطاء المحاولة السابقة: " + "؛ ".join(probs)
        except Exception as e:
            print("revise failed:", e)
    return None


def run_reply():
    text = (os.environ.get("REPLY_TEXT") or "").strip()
    replied = os.environ.get("REPLIED") or ""
    chat = str(os.environ.get("CHAT") or "")
    if TG_CHAT and chat and chat != str(TG_CHAT):
        print("ignored: chat mismatch")
        return
    m = re.search(r"🆔\s*(\d{8}-\d)", replied)
    if not m:
        tg_text("⚠️ اكتب ردّك بالرد (Reply) على رسالة الفيديو نفسها حتى أعرف أي فيديو تقصد.")
        return
    jid = m.group(1)
    job = load_json(JOBS / f"{jid}.json", None)
    if not job:
        tg_text(f"⚠️ لم أجد بيانات الفيديو {jid}.")
        return
    word = text.split()[0].lower().strip(".!،,") if text.split() else ""
    rest = text[len(text.split()[0]):].strip(" :،-") if text.split() else ""
    history = load_json(HISTORY, [])

    def set_status(status):
        job["status"] = status
        for h in history:
            if h["id"] == jid:
                h["status"] = status
        save_json(HISTORY, history)
        save_json(JOBS / f"{jid}.json", job)

    if word in ("ok", "okay", "اوك", "أوك", "موافق", "نعم"):
        set_status("approved")
        cap = (f"✅ تم الاعتماد — جاهز للنشر\n\n{job['title']}\n\n{job.get('caption', '')}\n\n{job.get('hashtags', '')}\n\n"
               f"⏰ وقت النشر المقترح: {job.get('publish_time', '')}\n🆔 {jid}")
        tg_video(job["file_id"], cap)
    elif word in ("no", "لا", "رفض", "مرفوض"):
        tg_text("🔄 تم تسجيل الرفض. جارٍ إعادة صناعة الفيديو وإصلاح ما ذكرت، وسيصلك خلال دقائق.")
        job["feedback"].append(rest)
        job["version"] = job.get("version", 1) + 1
        new_scenes = revise(job, rest)
        if new_scenes:
            job["scenes"] = new_scenes
        else:
            tg_text("ℹ️ تعذّرت إعادة كتابة النص، فسأغيّر الصور وأعيد الصناعة بالنص نفسه.")
        job["status"] = "pending"
        for h in history:
            if h["id"] == jid:
                h["status"] = "pending"
        save_json(HISTORY, history)
        produce(job)
    else:
        tg_text("لم أفهم ردّك. اكتب ok للموافقة، أو No ثم السبب للرفض (بالرد على رسالة الفيديو).")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "daily"
    try:
        if mode == "reply":
            run_reply()
        else:
            run_daily()
    except SystemExit:
        raise
    except Exception as e:
        traceback.print_exc()
        tg_text(f"⚠️ خطأ في النظام ({mode}): {str(e)[:700]}")
        raise


if __name__ == "__main__":
    main()
