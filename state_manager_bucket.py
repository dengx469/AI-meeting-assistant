from typing import Dict, Any, Set, Optional
import logging
import json
import os
import sys
from pathlib import Path
import time
from gmail_utils import send_reply
import config_bucket as config

logger = logging.getLogger(config.LOGGER_NAME)

# Paths can be either local paths or "gs://bucket/key"
PROCESSED_FILE = config.PROCESSED_FILE
EMAIL_OUT_DIR = config.EMAIL_OUT_DIR
LAST_STATE_FILE = config.LAST_STATE_FILE
LAST_HISTORY_FILE = config.LAST_HISTORY_FILE

# Try to import GCS client (optional)
try:
    from google.cloud import storage
    _HAS_GCS = True
except Exception:
    _HAS_GCS = False


# ========== Helper Functions ==========

def ensure_str_path(p: Any) -> str:
    """Ensure path is a string."""
    if isinstance(p, Path):
        return str(p)
    return str(p)


def is_gcs_path(path: str) -> bool:
    return path.startswith("gs://")


def split_gcs_path(path: str) -> (str, str):
    """Split 'gs://bucket/dir/file.json' -> ('bucket', 'dir/file.json')"""
    if not is_gcs_path(path):
        raise ValueError(f"Not a GCS path: {path}")
    without_scheme = path[len("gs://"):]
    parts = without_scheme.split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Invalid GCS path: {path}")
    return parts[0], parts[1]


def get_gcs_client() -> "storage.Client":
    if not _HAS_GCS:
        raise RuntimeError(
            "google-cloud-storage is not installed, "
            "but a gs:// path was configured."
        )
    return storage.Client()


def read_json(path: str) -> Optional[Any]:
    """Read JSON from local or GCS path."""
    if is_gcs_path(path):
        client = get_gcs_client()
        bucket_name, blob_name = split_gcs_path(path)
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_name)

        if not blob.exists():
            return None

        content = blob.download_as_text(encoding="utf-8").strip()
        if not content:
            return None
        return json.loads(content)
    else:
        p = Path(path)
        if not p.is_file():
            return None
        content = p.read_text(encoding="utf-8").strip()
        if not content:
            return None
        return json.loads(content)


def write_json(path: str, data: Any) -> None:
    """Write JSON to local or GCS path."""
    serialized = json.dumps(data, ensure_ascii=False, indent=2)

    if is_gcs_path(path):
        client = get_gcs_client()
        bucket_name, blob_name = split_gcs_path(path)
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        blob.upload_from_string(serialized, content_type="application/json")
    else:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(serialized, encoding="utf-8")


def ensure_file_exists(path: str) -> None:
    """Ensure a file or GCS blob exists (initialized as empty JSON)."""
    try:
        write_json(path, {})
    except Exception as e:
        logger.error(f"❌ Failed to initialize state file at {path}: {e}")
        sys.exit(1)


# ========== Business Functions ==========

def load_last_state() -> Dict[str, str]:
    """Load last_history_id + last_processed_date."""
    path = ensure_str_path(LAST_HISTORY_FILE)
    logger.debug(f"Read last_history_id from: {path}")

    try:
        data = read_json(path)
    except Exception as e:
        logger.warning(f"Failed to read last_history_id.json from {path}: {e}")
        return {}

    if data is None:
        logger.debug("last_history_id.json not found or empty, creating new one.")
        ensure_file_exists(path)
        return {}

    if not isinstance(data, dict):
        logger.warning(f"Invalid JSON format in {path}, resetting file.")
        ensure_file_exists(path)
        return {}

    if not data.get("last_history_id"):
        logger.warning("History ID missing in last_history_id.json, returning empty.")
        return {}

    return data


def save_last_state(history_id: str, last_date: str) -> None:
    """Save last_history_id + last_processed_date to file."""
    path = ensure_str_path(LAST_HISTORY_FILE)
    payload = {
        "last_history_id": history_id,
        "last_processed_date": last_date,
    }
    try:
        write_json(path, payload)
        logger.info(f"✅ Saved last_state to {path}")
    except Exception as e:
        logger.warning(f"Failed to save last_state.json to {path}: {e}")


def load_processed_ids() -> Set[str]:
    """Load processed message IDs."""
    path = ensure_str_path(PROCESSED_FILE)
    logger.debug(f"Load processed_ids from: {path}")

    try:
        data = read_json(path)
    except Exception as e:
        logger.warning(f"Failed to read processed_ids.json from {path}: {e}")
        return set()

    if data is None:
        return set()

    if isinstance(data, list):
        return set(map(str, data))

    if isinstance(data, dict) and "ids" in data and isinstance(data["ids"], list):
        return set(map(str, data["ids"]))

    logger.warning(f"Invalid format in {path}, expected list or {{'ids': [...]}}.")
    return set()


def save_processed_ids(ids: Set[str]) -> None:
    """Save processed message IDs."""
    path = ensure_str_path(PROCESSED_FILE)
    payload = sorted(map(str, ids))

    try:
        write_json(path, payload)
        logger.info(f"✅ Saved processed_ids to {path} (count={len(payload)})")
    except Exception as e:
        logger.warning(f"Failed to save processed_ids.json to {path}: {e}")

def update_last_history_file(service: Any) -> None:
    """
    Update LAST_HISTORY_FILE with latest Gmail historyId.

    - 支持本地文件路径和 GCS 路径（gs://...）
    - 仅在成功获取到 historyId 时更新
    """
    try:
        profile = service.users().getProfile(userId="me").execute()
        latest_hid = profile.get("historyId")

        if not latest_hid:
            logger.warning("Failed to get latest historyId, skip update.")
            return

        data = {
            "last_history_id": latest_hid,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        }

        path = ensure_str_path(LAST_HISTORY_FILE)
        write_json(path, data)

        logger.info(
            f"✅ Updated last_history_id at {path}, current latest historyId = {latest_hid}"
        )

    except Exception as e:
        logger.error(f"❌ Failed to update last_history_id.json: {e}")

    
def ensure_failed_file_exists(service_gmail):
    """
    Ensure FAILED_FILE exists (local or GCS) and is a valid dict.

    """
    path = ensure_str_path(config.FAILED_FILE)

    # 1. Attemp to read
    try:
        data = read_json(path)
    except Exception as e:
        logger.error(f"❌ Failed to read FAILED_FILE at {path}: {e}")
        subject = "⚠️ Alert: failed_ids.json read failed"
        body = (
            f"The system failed to read the required file {path}.\n"
            f"Error: {e}\n\n"
            "Please check storage permission or GCS configuration."
        )
        try:
            send_reply(service_gmail, None, MY_EMAIL, subject, body)
        except Exception as mail_err:
            logger.error(f"⚠️ Failed to send alert email: {mail_err}")
        return "Error"

    # 2. Return Null Dict if failed to get the file or the file is empty
    if data is None:
        try:
            write_json(path, {})
            logger.warning(f"⚠️ {path} was missing or empty. Created a new empty file.")
            return {}
        except Exception as e:
            logger.error(f"❌ Failed to create empty FAILED_FILE at {path}: {e}")
            subject = "⚠️ Alert: failed_ids.json creation failed"
            body = (
                f"The system failed to create the required file {path}.\n"
                f"Error: {e}\n\n"
                "This may indicate a permission or storage issue."
            )
            try:
                send_reply(service_gmail, None, MY_EMAIL, subject, body)
            except Exception as mail_err:
                logger.error(f"⚠️ Failed to send alert email: {mail_err}")
            return "Error"

    # 3. Reset the file to Null if the format is wrong
    if not isinstance(data, dict):
        logger.warning(
            f"⚠️ Invalid format in {path}, expected dict but got {type(data)}. Resetting file."
        )
        try:
            write_json(path, {})
            return {}
        except Exception as e:
            logger.error(f"❌ Failed to reset FAILED_FILE at {path}: {e}")
            subject = "⚠️ Alert: failed_ids.json reset failed"
            body = (
                f"The system failed to reset the invalid file {path}.\n"
                f"Error: {e}\n\n"
                "Please check storage or deployment configuration."
            )
            try:
                send_reply(service_gmail, None, MY_EMAIL, subject, body)
            except Exception as mail_err:
                logger.error(f"⚠️ Failed to send alert email: {mail_err}")
            return "Error"

    # 4. Return data
    return data
