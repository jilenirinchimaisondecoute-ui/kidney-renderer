"""نشر فيديو على حساب المالك في TikTok (Content Posting API - Direct Post، رفع ملف)."""
import os, json, base64, hashlib, time, urllib.request, urllib.parse, urllib.error
from pathlib import Path

TOKEN_FILE = Path("state/tiktok_token.enc")
API = "https://open.tiktokapis.com"


def _fernet():
    from cryptography.fernet import Fernet
    key = base64.urlsafe_b64encode(hashlib.sha256(os.environ["TT_PASS"].encode()).digest())
    return Fernet(key)


def enabled():
    return TOKEN_FILE.exists() and all(os.environ.get(k) for k in ("TT_CLIENT_KEY", "TT_CLIENT_SECRET", "TT_PASS"))


def _http(url, data=None, headers=None, method=None, timeout=120):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode() or "{}"
    except urllib.error.HTTPError as e:
        body = e.read().decode() or "{}"
    try:
        return json.loads(body)
    except Exception:
        return {"raw": body[:300]}


def _refresh():
    tok = json.loads(_fernet().decrypt(TOKEN_FILE.read_bytes()))
    data = urllib.parse.urlencode({
        "client_key": os.environ["TT_CLIENT_KEY"].strip(), "client_secret": os.environ["TT_CLIENT_SECRET"].strip(),
        "grant_type": "refresh_token", "refresh_token": tok["refresh_token"]}).encode()
    r = _http(API + "/v2/oauth/token/", data, {"Content-Type": "application/x-www-form-urlencoded"})
    if "access_token" not in r:
        raise RuntimeError(f"refresh failed: {r.get('error')} {r.get('error_description')}")
    tok.update({k: r[k] for k in ("access_token", "refresh_token", "expires_in", "scope") if k in r})
    TOKEN_FILE.write_bytes(_fernet().encrypt(json.dumps(tok).encode()))
    return tok["access_token"]


def post_video(path, title):
    """يرجع نصاً يصف النتيجة. يرفع الملف كاملاً (حتى 64MB) في دفعة واحدة."""
    access = _refresh()
    auth = {"Authorization": f"Bearer {access}", "Content-Type": "application/json; charset=UTF-8"}
    privacy = os.environ.get("TT_PRIVACY", "SELF_ONLY")
    info = _http(API + "/v2/post/publish/creator_info/query/", b"{}", auth, "POST")
    opts = (info.get("data") or {}).get("privacy_level_options") or []
    if opts and privacy not in opts:
        privacy = opts[0]
    size = os.path.getsize(path)
    body = {"post_info": {"title": title[:2200], "privacy_level": privacy,
                          "disable_duet": False, "disable_comment": False, "disable_stitch": False},
            "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": size, "total_chunk_count": 1}}
    r = _http(API + "/v2/post/publish/video/init/", json.dumps(body).encode(), auth, "POST")
    err = r.get("error") or {}
    if err.get("code") not in (None, "ok"):
        raise RuntimeError(f"init: {err.get('code')} {err.get('message')}")
    d = r["data"]
    up = urllib.request.Request(d["upload_url"], data=Path(path).read_bytes(), method="PUT", headers={
        "Content-Type": "video/mp4", "Content-Length": str(size), "Content-Range": f"bytes 0-{size - 1}/{size}"})
    with urllib.request.urlopen(up, timeout=300) as resp:
        if resp.status not in (200, 201):
            raise RuntimeError(f"upload status {resp.status}")
    status = "?"
    for _ in range(12):
        time.sleep(5)
        s = _http(API + "/v2/post/publish/status/fetch/", json.dumps({"publish_id": d["publish_id"]}).encode(), auth, "POST")
        status = (s.get("data") or {}).get("status", "?")
        if status in ("PUBLISH_COMPLETE", "FAILED"):
            if status == "FAILED":
                status += f" ({(s.get('data') or {}).get('fail_reason')})"
            break
    return f"TikTok: {status} (privacy={privacy})"
