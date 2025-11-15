"""
Centralized configuration module.

Load environment variables here so other modules can import `config` and
read the same values at runtime (e.g. `config.PROCESSED_FILE`).

Notes:
- Importing `config` reads environment variables when the module is first
  imported. If you need to change env vars at runtime, set `os.environ[...]`
  before importing modules that read config, or call `config.reload()` and
  reference attributes off the `config` module (not copied constants).
"""
from __future__ import annotations
import os,platform
from pathlib import Path
IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"
if IS_WINDOWS:
    default_dir = "D:\\tiger\\project\\meetinghelper\\test"  # Windows 路径
else:
    default_dir = "/home/dengxiao910/email_state"  # Linux / macOS 路径
DEFAULT_DIR=Path(default_dir)

def detect_app_env() -> str:
    """
    Automatic runtime environment detection:
    If APP_ENV is explicitly set, it takes priority (local / gcs / container ...)
    If K_SERVICE exists, it is considered to be in a Cloud Run container (can default to gcs or container)
    If /.dockerenv exists, it is considered to be in a generic Docker container
    Otherwise, it is considered a local environment
    """
    explicit = os.getenv("APP_ENV")
    if explicit:
        return explicit.lower()

    # Cloud Run / Cloud Functions 等（Cloud Run 一定有 K_SERVICE）
    if os.getenv("K_SERVICE"):
        # Check cloud run mode
        return "gcs"

    if os.path.exists("/.dockerenv"):
        # Check local mode
        return "local"

    # local mode is default
    return "local"

APP_ENV = detect_app_env()




LOGGER_NAME = "gmail_push_logger"
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "GEMINI").upper()  # GEMINI or DEEPSEEK
# Gemini (AI Studio)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-pro")  # or gemini-1.5-flash

# DeepSeek (kept as fallback / optional)
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
# Defaults — override with environment variables

if IS_WINDOWS:
    default_dir = "D:\\tiger\\project\\meetinghelper\\test"  # Windows Path
else:
    default_dir = "/home/dengxiao910/email_state"  # Linux / macOS Path

DEFAULT_TOKEN_FILE = DEFAULT_DIR / "gmail_token.json"
EMAIL_OUT_DIR = Path(os.getenv("EMAIL_OUT_DIR", default_dir))
PROCESSED_FILE = Path(os.getenv("PROCESSED_FILE", str(Path(EMAIL_OUT_DIR) / "processed_ids.json")))
LAST_STATE_FILE = Path(os.getenv("LAST_STATE_FILE", str(Path(EMAIL_OUT_DIR) / "last_history_id.json")))
LAST_HISTORY_FILE = Path(os.getenv("LAST_HISTORY_FILE", str(Path(EMAIL_OUT_DIR) / "last_history_id.json")))
FAILED_FILE = Path(os.getenv("FAILED_FILE", str(Path(EMAIL_OUT_DIR) / "failed_ids.json")))
DEFAULT_TZ = Path(os.getenv("DEFAULT_TZ", "Asia/Shanghai"))
MY_EMAIL = os.getenv("GMAIL_SENDER", "dengxiao910@gmail.com").lower()
TOKEN_FILE = Path(os.getenv("GMAIL_TOKEN_FILE") or DEFAULT_TOKEN_FILE)
CLIENT_ID = "425577127921-5a7rajeeh4gqbljkgt0vobmjbeh8qgsm.apps.googleusercontent.com"
PROJECT_ID = "meetinghelper-475009"
REFRESH_TOKEN= "1//06WXbXVg8oWZgCgYIARAAGAYSNwF-L9IrToODIKaDofmh2PwezTfNLUJJNvnUpYAiw5KNfNqFvj8Nts6cxHdBBlRGWGVna-wiuSc"
CLIENT_SECRET= "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"
STATE_BUCKET = "meeting-helper-email-state-475009"




# Ensure directory exists when possible (best-effort)
try:
    Path(EMAIL_OUT_DIR).mkdir(parents=True, exist_ok=True)
except Exception:
    # Directory creation may fail in restricted environments; callers should
    # handle write errors as appropriate.
    pass

if APP_ENV == "gcs":
    if not STATE_BUCKET:
        raise RuntimeError("APP_ENV=gcs, Failed to get STATE_BUCKET from environment")
    PROCESSED_FILE = f"gs://{STATE_BUCKET}/state/processed_ids.json"
    LAST_HISTORY_FILE = f"gs://{STATE_BUCKET}/state/last_history_id.json"
    EMAIL_OUT_DIR = str(DEFAULT_DIR / "emails")
    FAILED_FILE = f"gs://{STATE_BUCKET}/state/failed_ids.json"
else:
    # local / container 
    PROCESSED_FILE = DEFAULT_DIR / "processed_ids.json"
    LAST_HISTORY_FILE = DEFAULT_DIR / "last_history_id.json"
    EMAIL_OUT_DIR =  DEFAULT_DIR/ "emails"
    FAILED_FILE = Path(os.getenv("FAILED_FILE", str(DEFAULT_DIR / "failed_ids.json")))

LAST_STATE_FILE = LAST_HISTORY_FILE


def reload() -> None:
    """Reload values from environment (call if you modify os.environ at runtime).

    Use patterns like `import config; config.reload()` and then reference
    `config.PROCESSED_FILE` to pick up changes.
    """
    global EMAIL_OUT_DIR, PROCESSED_FILE, LAST_STATE_FILE, LAST_HISTORY_FILE, DEFAULT_TZ
    if IS_WINDOWS:
        default_dir = "D:\\tiger\\project\\meetinghelper\\test"  # Windows path
    else:
        default_dir = "/home/dengxiao910/email_state"  # Linux / macOS path
    DEFAULT_DIR=Path(default_dir)
    EMAIL_OUT_DIR = Path(os.getenv("EMAIL_OUT_DIR", default_dir))
    PROCESSED_FILE = Path(os.getenv("PROCESSED_FILE", str(Path(EMAIL_OUT_DIR) / "processed_ids.json")))
    LAST_STATE_FILE = Path(os.getenv("LAST_STATE_FILE", str(Path(EMAIL_OUT_DIR) / "last_history_id.json")))
    LAST_HISTORY_FILE = Path(os.getenv("LAST_HISTORY_FILE", str(Path(EMAIL_OUT_DIR) / "last_history_id.json")))
    FAILED_FILE = Path(os.getenv("FAILED_FILE", str(Path(EMAIL_OUT_DIR) / "failed_ids.json")))
    DEFAULT_TZ = Path(os.getenv("DEFAULT_TZ", "Asia/Shanghai"))
    MY_EMAIL = os.getenv("GMAIL_SENDER", "dengxiao910@gmail.com").lower()
    TOKEN_FILE = Path(os.getenv("GMAIL_TOKEN_FILE") or DEFAULT_TOKEN_FILE)
    if APP_ENV == "gcs":
        if not GCS_BUCKET:
            raise RuntimeError("APP_ENV=gcs, Falied to get STATE_BUCKET from environment")
            PROCESSED_FILE = f"gs://{STATE_BUCKET}/state/processed_ids.json"
            LAST_HISTORY_FILE = f"gs://{STATE_BUCKET}/state/last_history_id.json"
            EMAIL_OUT_DIR = str(DEFAULT_DIR / "emails")
    else:
    # local / container 
        PROCESSED_FILE = DEFAULT_DIR / "processed_ids.json"
        LAST_HISTORY_FILE = DEFAULT_DIR / "last_history_id.json"
        EMAIL_OUT_DIR = DEFAULT_DIR / "emails"

LAST_STATE_FILE = LAST_HISTORY_FILE


