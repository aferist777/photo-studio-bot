import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_env() -> dict:
    env = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


_E = _load_env()


def _get(key: str, default: str = "") -> str:
    return _E.get(key) or os.getenv(key, default)


BOT_TOKEN = _get("TELEGRAM_BOT_TOKEN")
KIE_API_KEY = _get("KIE_API_KEY")

DB_PATH = ROOT / "bot.db"

# Catalog thumbnails built from the vault previews; served by the admin panel.
PREVIEW_DIR = ROOT / "assets" / "previews"
# Reference selfies. These are personal data: /forget wipes the whole per-user
# folder, so nothing but face references may ever live under FACE_DIR.
FACE_DIR = ROOT / "media" / "faces"
RESULT_DIR = ROOT / "media" / "results"
for _dir in (PREVIEW_DIR, FACE_DIR, RESULT_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

_DEFAULT_VAULT = (
    Path.home() / "OneDrive" / "Desktop" / "mavault" / "mavault"
    / "AI" / "PROMPTS-INSTRUCTIONS" / "PHOTOSESSIONS PROMPTS"
)
VAULT_DIR = Path(_get("VAULT_DIR") or _DEFAULT_VAULT)
# Folder name in the vault -> gender stored on the template.
VAULT_GENDERS = {"GIRLS": "female", "BOYS": "male"}

GENDER_LABELS = {"female": "Women", "male": "Men"}

# Admin panel. Loopback on purpose: there is no authentication yet, and the
# panel exposes both payments and other people's face photos.
ADMIN_HOST = "127.0.0.1"
ADMIN_PORT = int(_get("ADMIN_PORT", "8766"))

# Proofreading pass of the imported prompts (opt-in, `--proofread`). Same
# OpenAI-compatible kie endpoint gop-tarot-bot uses for its readings.
GEMINI_URL = "https://api.kie.ai/gemini-3-5-flash-openai/v1/chat/completions"
GEMINI_MODEL = "gemini-3-5-flash"
