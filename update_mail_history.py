import logging
import os
import json
import time
from logger_config import logger
from gmail_utils import send_reply
import config_bucket as config

LAST_HISTORY_FILE = os.getenv("LAST_HISTORY_FILE", "/home/dengxiao910/email_state/last_history_id.json")
#LAST_HISTORY_FILE = os.getenv("LAST_HISTORY_FILE", "D:/tiger/project/meetinghelper/test/last_history_id.json")



import json
import os
import sys
from logger_config import logger

FAILED_FILE = config.FAILED_FILE
MY_EMAIL = config.MY_EMAIL

def ensure_failed_file_exists(service_gmail) -> dict:
    """
    Ensure failed_ids.json exists and is readable.
    If it exists, read and return its content as a dict.
    If missing, create an empty dict file.
    Exit program if creation or reading fails.
    """
    # 文件不存在 → 创建
    if not os.path.exists(FAILED_FILE):
        try:
            os.makedirs(os.path.dirname(FAILED_FILE), exist_ok=True)
            with open(FAILED_FILE, "w", encoding="utf-8") as f:
                json.dump({}, f)
            logger.warning(f"⚠️ {FAILED_FILE} was missing. Created a new empty file.")
            return {}
        except Exception as e:
            subject = "⚠️ Alert: failed_ids.json creation failed"
            body = (
                f"The system failed to create the required file {FAILED_FILE}.\n"
                f"Error: {e}\n\n"
                "This may indicate a permission or storage issue.\n"
                "The service will now shut down to avoid inconsistent state."
            )
            try:
                send_reply(service_gmail, None, MY_EMAIL, subject, body)
            except Exception as mail_err:
                logger.error(f"⚠️ Failed to send alert email: {mail_err}")
            sys.exit(1)

    # 文件存在 → 读取内容
    try:
        with open(FAILED_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not data:
                logger.warning("⚠️ failed_ids.json is empty.")
            else:
                logger.info(f"✅ Loaded {len(data)} failed records.")
            logger.info(f"✅ Verified {FAILED_FILE} is available and readable.")
            return data
    except Exception as e:
        subject = "⚠️ Alert: failed_ids.json corrupted"
        body = (
            f"The file {FAILED_FILE} cannot be parsed correctly.\n"
            f"Error: {e}\n\n"
            "This may indicate a write failure or manual modification.\n"
            "The service will now shut down to prevent data inconsistency."
        )
        try:
            send_reply(service_gmail, None, MY_EMAIL, subject, body)
        except Exception as mail_err:
            logger.error(f"⚠️ Failed to send alert email: {mail_err}")
        sys.exit(1)


def create_last_history_file():
    """
    🚀 Create last_history_id.json if run at first time.
    """
    try:
        os.makedirs(os.path.dirname(LAST_HISTORY_FILE), exist_ok=True)
        with open(LAST_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump({"last_history_id": ""}, f)
        logger.info(f"initialize last_history_id.json: {LAST_HISTORY_FILE}")
    except Exception as e:
        logger.error(f"Create {LAST_HISTORY_FILE} Failed: {e}")

"""
def load_last_history_id() -> str | None:
    if os.path.exists(LAST_HISTORY_FILE):
        try:
            with open(LAST_HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f).get("last_history_id")
        except Exception:
            logger.warning("Read last_history_id.json Failed")
    return None


def save_last_history_id(hid: str):
    try:
        with open(LAST_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump({"last_history_id": hid}, f)
    except Exception:
        logger.warning("Save last_history_id.json Failed")

"""    
def update_last_history_file(service):
    """Update last_history_id.json with latest historyId"""
    try:
        profile = service.users().getProfile(userId="me").execute()
        latest_hid = profile.get("historyId")

        if not latest_hid:
            logger.warning("Failed to get latest historyId,skip.")
            return

        data = {
            "last_history_id": latest_hid,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        }

        with open(LAST_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"✅ Updated {LAST_HISTORY_FILE},current latest historyId = {latest_hid}")

    except Exception as e:
        logger.error(f"Update last_history_id.json Failed: {e}")


import json, sys, time, os
from datetime import datetime

def record_failed_event(service_gmail, msg_id: str, reason: str):
    """
Safely write the email IDs that failed processing to failed_ids.json.
If writing fails or the file is corrupted, send an email alert to the administrator and exit the program.
    """
    # Confirm the file exists and readable 
    if not os.path.exists(FAILED_FILE):
        logger.error(f"⚠️ {FAILED_FILE} missing before write attempt. Attempting to recreate...")
        try:
            os.makedirs(os.path.dirname(FAILED_FILE), exist_ok=True)
            with open(FAILED_FILE, "w", encoding="utf-8") as f:
                json.dump({}, f)
            logger.info(f"✅ Recreated missing {FAILED_FILE}")
        except Exception as e:
            subject = "⚠️ Alert: failed_ids.json recreate failed"
            body = (
                f"The system attempted to recreate {FAILED_FILE} but failed.\n"
                f"Error: {e}\n\n"
                "System will exit to avoid inconsistent state."
            )
            try:
                send_reply(service_gmail, None, MY_EMAIL, subject, body)
            except Exception as mail_err:
                logger.error(f"⚠️ Failed to send alert email: {mail_err}")
            sys.exit(1)

    # 🔹 读取已有文件内容
    try:
        with open(FAILED_FILE, "r", encoding="utf-8") as f:
            failed_data = json.load(f)
            if not isinstance(failed_data, dict):
                raise ValueError("File content is not a dict")
    except Exception as e:
        subject = "⚠️ Alert: failed_ids.json read error"
        body = (
            f"Unable to read or parse {FAILED_FILE}.\n"
            f"Error: {e}\n\n"
            "The service will now shut down to prevent data corruption."
        )
        try:
            send_reply(service_gmail, None, MY_EMAIL, subject, body)
        except Exception as mail_err:
            logger.error(f"⚠️ Failed to send alert email: {mail_err}")
        sys.exit(1)

    # 🔹 写入失败记录
    failed_data[msg_id] = {
        "reason": reason[:200],
        "timestamp": datetime.utcnow().isoformat()
    }

    # 🔹 限制最大记录条数
    MAX_FAILED = 200
    if len(failed_data) > MAX_FAILED:
        failed_data = dict(list(failed_data.items())[-MAX_FAILED:])

    # 🔹 安全写入（临时文件替换机制）
    temp_path = FAILED_FILE + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(failed_data, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, FAILED_FILE)
        logger.warning(f"🧩 recorded failed event {msg_id} ({reason[:80]})")
    except Exception as e:
        subject = "⚠️ Alert: failed_ids.json write error"
        body = (
            f"Failed to write to {FAILED_FILE}.\n"
            f"Error: {e}\n\n"
            "The service will now shut down to avoid partial data writes."
        )
        try:
            send_reply(service_gmail, None, MY_EMAIL, subject, body)
        except Exception as mail_err:
            logger.error(f"⚠️ Failed to send alert email: {mail_err}")
        sys.exit(1)

