"""Exchange the one-time TikTok authorization code for tokens and store them encrypted."""
import os, json, base64, hashlib, sys, urllib.request, urllib.parse
from cryptography.fernet import Fernet

CODE = os.environ["TT_CODE"].strip()
if "code=" in CODE:  # allow pasting a whole URL
    CODE = urllib.parse.parse_qs(urllib.parse.urlparse(CODE).query)["code"][0]
CODE = urllib.parse.unquote(CODE)
_ck=os.environ.get("TT_CLIENT_KEY","").strip(); _cs=os.environ.get("TT_CLIENT_SECRET","").strip()
print("diag: client_key len=%d starts=%s | client_secret len=%d | code len=%d | pass set=%s" % (len(_ck), _ck[:4], len(_cs), len(CODE), bool(os.environ.get("TT_PASS"))))
data = urllib.parse.urlencode({
    "client_key": os.environ["TT_CLIENT_KEY"].strip(),
    "client_secret": os.environ["TT_CLIENT_SECRET"].strip(),
    "code": CODE,
    "grant_type": "authorization_code",
    "redirect_uri": "https://jilenirinchimaisondecoute-ui.github.io/kidney-renderer/callback.html",
}).encode()
req = urllib.request.Request("https://open.tiktokapis.com/v2/oauth/token/", data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
try:
    r = json.load(urllib.request.urlopen(req, timeout=60))
except urllib.error.HTTPError as e:
    print("HTTP", e.code, e.read().decode()[:500]); sys.exit(1)
if "access_token" not in r:
    print("TikTok error:", {k: r.get(k) for k in ("error", "error_description")}); sys.exit(1)
tok = {k: r[k] for k in ("access_token", "refresh_token", "open_id", "scope", "expires_in") if k in r}
key = base64.urlsafe_b64encode(hashlib.sha256(os.environ["TT_PASS"].encode()).digest())
os.makedirs("state", exist_ok=True)
open("state/tiktok_token.enc", "wb").write(Fernet(key).encrypt(json.dumps(tok).encode()))
print("OK: token saved (encrypted). scope =", tok.get("scope"))
