#!/usr/bin/env python3
# coding: utf-8


from flask import Flask, request, jsonify
import config_bucket as config
import logging,os,sys,json
from pathlib import Path
from logger_config import logger
LOGGER_NAME = "gmail_push_logger"
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG").upper()




TOKEN_FILE = config.TOKEN_FILE  
TOKEN_JSON_ENV = os.getenv("GMAIL_TOKEN_JSON") or os.getenv("TOKEN_JSON")  
if not TOKEN_JSON_ENV:
    import logging
    logging.getLogger(LOGGER_NAME).error("❌ TOKEN_JSON/GMAIL_TOKEN_JSON not set")
else:
    Path(os.path.dirname(TOKEN_FILE)).mkdir(parents=True, exist_ok=True)
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(TOKEN_JSON_ENV)
    logging.getLogger(LOGGER_NAME).info(f"✅ token.json written to {TOKEN_FILE}")


logger.info("Flask app created; module imported,App_safe")


# Flask app
app = Flask(__name__)
import os, psutil, threading, time, logging

def log_mem():
    while True:
        mem = psutil.Process(os.getpid()).memory_info().rss / 1024**2
        logger.info(f"[MEMORY USAGE] {mem:.2f} MB")
        time.sleep(10)

threading.Thread(target=log_mem, daemon=True).start()
logger.info("✅ Memory monitor thread started")

@app.get("/healthz")
def healthz():
    return "ok", 200

import json
import base64, time, os, json
import time
import googleapiclient.errors
from datetime import datetime
from typing import Optional, Dict, Any, List
from calendar_utils import create_calendar_event, send_meeting_invite


import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from email.mime.text import MIMEText
from time_parser import get_sender_timezone,parse_human_time
from gmail_utils import (
    get_gmail_service, 
    fetch_latest_messages,
    mark_email_as_processed
    )
from state_manager_bucket import (
    update_last_history_file,
    ensure_failed_file_exists,
    load_last_state,
    save_last_state,
    load_processed_ids,
    save_processed_ids
    )

    

import gmail_utils
from message_handle import process_single_message


# --- logging setup (module-level) -------------------------------------------
import sys
import os


SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar"
]


EMAIL_OUT_DIR = config.EMAIL_OUT_DIR
FAILED_FILE = config.FAILED_FILE
GMAIL_TOKEN_FILE = os.getenv("GMAIL_TOKEN_FILE", "token.json")
MAX_FETCH = int(os.getenv("MAX_FETCH", "10"))
DEFAULT_TZ = os.getenv("DEFAULT_TZ", "Asia/Shanghai")
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG").upper()
DEBUG_GMAIL_WEBHOOK = os.getenv("DEBUG_GMAIL_WEBHOOK", "0") == "1"
PORT = int(os.getenv("PORT", "8080"))
LOGGER_NAME = "gmail_push_logger"
MY_EMAIL = config.MY_EMAIL


DEEPSEEK_API_KEY = config.DEEPSEEK_API_KEY
DEEPSEEK_API_URL = config.DEEPSEEK_API_URL or os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")
GEMINI_API_KEY = config.GEMINI_API_KEY
LLM_PROVIDER = config.LLM_PROVIDER



# Make sure the logger output directory exists
os.makedirs(EMAIL_OUT_DIR, exist_ok=True)

logger.info("✅ Environment variable loading completed")
logger.info(f"📂 EMAIL_OUT_DIR={EMAIL_OUT_DIR}")
logger.info(f"🕒 DEFAULT_TZ={DEFAULT_TZ}")
logger.info(f"🪵 LOG_LEVEL={LOG_LEVEL}")
logger.info(f"🤖 DEEPSEEK_API_KEY={'Already set' if DEEPSEEK_API_KEY else 'not set'}")

os.makedirs(EMAIL_OUT_DIR, exist_ok=True)
LAST_HISTORY_FILE = os.path.join(EMAIL_OUT_DIR, "last_history_id.json")
PROCESSED_FILE = os.path.join(EMAIL_OUT_DIR, "processed_ids.json")


logger = logging.getLogger(LOGGER_NAME)
if not logger.handlers:  #Avoid adding handlers repeatedly (Gunicorn multi-process/multi-import scenario)
    #level = os.getenv("LOG_LEVEL", "INFO").upper()
    level = "DEBUG"
    logger.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)  # Cloud Run/Cloud Logging reads stdout/stderr
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# Make the noisy log of the third-party library a little quieter (optional)
logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.WARNING)

# A file that records processed messages (please ensure that the container has write permissions when deploying, or use external storage instead)

# Maximum number of emails pulled at one time
MAX_RESULTS = int(os.getenv("MAX_FETCH", 10))

# Gmail OAuth token file (generated through local gentoken910.py and uploaded)
TOKEN_FILE = os.getenv("GMAIL_TOKEN_FILE", "token.json")
#LAST_HISTORY_FILE = "last_history_id.json"



LAST_STATE_FILE = os.path.join(EMAIL_OUT_DIR, "last_state.json")
DEFAULT_TZ = os.getenv("DEFAULT_TZ", "Asia/Shanghai")

from datetime import datetime, timedelta
import re
import pytz
import dateparser
from dateutil import tz as dateutil_tz
from email.utils import parsedate_tz

logger = logging.getLogger(__name__)





# -------------------------
# Save email to file
# -------------------------
from email.utils import formataddr

def save_email_to_file(to: str, subject: str, body: str, thread_id: str = None) -> str:
    """Save email to file, not send"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    thread_str = f"_thread_{thread_id}" if thread_id else ""
    filename = os.path.join(EMAIL_OUT_DIR, f"email_{timestamp}{thread_str}.txt")
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"To: {to}\nSubject: {subject}\n\n{body}\n")
    return filename

def is_system_or_notification_email(msg: dict, my_email: str) -> bool:
    """
    Return True if this email should be ignored by the meeting helper:
    - Google Calendar / system notifications
    - Auto-generated / auto-replies
    - Delivery failure, etc.
    """
    payload = msg.get("payload", {})
    headers = {h.get("name", "").lower(): h.get("value", "") 
               for h in payload.get("headers", [])}

    from_ = headers.get("from", "").lower()
    subject = headers.get("subject", "").lower()
    auto_submitted = headers.get("auto-submitted", "").lower()
    precedence = headers.get("precedence", "").lower()

    # 1) Auto respond email from google calendar
    if "calendar-notification@google.com" in from_:
        return True

    # 2) Google / mailer-daemon 
    if "mailer-daemon" in from_ or "postmaster@" in from_:
        return True

    # 3) 
    if auto_submitted and auto_submitted != "no":
        return True
    if precedence in ("bulk", "list", "auto_reply", "auto-reply"):
        return True

    # 4) The emails sent to me myself
    #    
    if my_email.lower() in from_ and (
        "notification" in subject or "confirmation" in subject
    ):
        return True

    # If the email body begins with a script (e.g., a block of Python code pasted for an LLM), 
    # this usually isn't a natural language meeting request and should be skipped to prevent misjudgment by the LLM.5)
    try:
        # Capture part of body
        body = ""
        if "parts" in payload:
            for part in payload["parts"]:
                if part.get("mimeType") == "text/plain" and "data" in part.get("body", {}):
                    import base64
                    body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", "ignore")
                    break
        else:
            data = payload.get("body", {}).get("data")
            if data:
                import base64
                body = base64.urlsafe_b64decode(data).decode("utf-8", "ignore")

        first_line = body.lstrip().splitlines()[0] if body else ""
        if first_line.startswith("#!/usr/bin/env python3"):
            return True
    except Exception:
        pass

    return False


# -------------------------
# Main work flow. Fetch the newest email from last time. Call LLM to check the intention and time of meeting.send reply to attendees. 
# -------------------------
@app.route("/gmail-webhook", methods=["POST"])
#@app.route("/gmail-webhook", methods=["POST", "GET"])
def gmail_webhook():
#def main():
    """
    Trigger by the gmail webhook
    
    """
    
    logger = logging.getLogger(LOGGER_NAME)

    if not logger.handlers:
        level = os.getenv("LOG_LEVEL", "DEBUG").upper()
        logger.setLevel(level)

        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        logger.info(f"intializing logger, LOG_LEVEL={logging.getLevelName(logger.level)}")

    if LLM_PROVIDER == "GEMINI":
        if GEMINI_API_KEY == None:
            logger.error("GEMINI_API_KEY not set")
            return ("", 204)
            #return  jsonify({"status": "no_messages"}),204 #return unfer webhook mode
            #return
    else:
        if DEEPSEEK_API_KEY == None:
                logger.warning("DEEPSEEK_API_KEY not set, using GEMINI as LLM provider")
                return ("", 204)
                #return  jsonify({"status": "no_messages"}),204  # return unfer webhook mode
                #return#


    

    try:
        logger.info("📩 get trigger from webhook")
        service,creds = get_gmail_service()
        state = load_last_state()
        last_hid = state.get("last_history_id")
        last_date = state.get("updated_at")
        msg_objs = []
        # Exctract the failed ids and retry. 
        failed_data=ensure_failed_file_exists(service)
        if failed_data == "Error":
            SystemExit()
        retry_failed = [] # The list for saving the failed ids after retrying.
        if failed_data:
            logger.info(f"🔄 Retrying {len(failed_data)} previously failed messages.")
            try:
                for item in failed_data:
                    msg_id = None
                    msg_id=item["msg_id"]
                    # Fetch the message by ID
                    msg_obj = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
                    logger.info(f"📧 Processing msg_id={msg_id}")

            # Process the message
                    success = process_single_message(msg_obj, service,MY_EMAIL,creds)

                    if not success:
                        logger.warning(f"⚠️ Failed to process msg_id={msg_id}")
                        retry_failed.append(msg_id)
                    else:
                        mark_email_as_processed(service, msg_id,label_name=None, also_mark_read=True)
                        
            except Exception as e:
                    logger.error(f"❌ Failed to process msg_id={msg_id} :{e}")
                    retry_failed.append(msg_id)

    # Update the failed file with remaining failed ids
            with open(FAILED_FILE, "w") as f:
                json.dump(retry_failed, f, indent=2, ensure_ascii=False)
        logger.info(f"✅ Retry done：Sucess {len(failed_data) - len(retry_failed)}，Failed {len(retry_failed)}")
        state = load_last_state()

        if not state:
            # Failed to load last_state.json, probably the first time running.get the latest messages recent 30 days.
            logger.info("First time running or failed to load last_state.json. Fetching recent 30 days emails.")
            now = int(time.time())
            days_ago = now - 30 * 24 * 3600
            ten_min_ago = now - 10 * 60  #only fetch email 10 mins ago for testing
            msg_objs = fetch_latest_messages(service, after_timestamp=ten_min_ago)
            #create_last_history_file()
            logger.info(f"initializing historyId: {last_hid}, last_date: {last_date} from last_history_id.json file. Fetching recent 30 days emails.")
        else:
            # fetch the messages after last_date if the last_date is set
            last_hid = state.get("last_history_id")
            last_date = state.get("updated_at")
            logger.info(f"lastest historyId: {last_hid}, lastest processed date: {last_date},fetching messages after {last_date}")
            if last_date:
                dt = datetime.strptime(last_date, "%Y-%m-%d %H:%M:%S")
                after_ts = int(dt.timestamp())
                msg_objs = fetch_latest_messages(service, after_timestamp=after_ts)
            else:
                msg_objs = []

        if not msg_objs:
            logger.info("No new messages found.")
            try:
                update_last_history_file(service)
                logger.info("✅ Updated last_history_id.json to the latest historyId.")
            except Exception as e:
                logger.warning(f"⚠️ Failed to update last_history_id.json: {e}")


            return ("", 204)
            #return jsonify({"status": "no_messages"}),204  # return unfer webhook mode
            #return

        # === process messages ===
        last_msg_time = None    
        failed_list = [] 
        for msg in msg_objs:
            msg_id = msg.get("id")
            if is_system_or_notification_email(msg, MY_EMAIL):#Filter the  Automated Emails
                logger.info(f"⏭️ Skip system/notification email msg_id={msg_id}")
                continue
            result=process_single_message(msg, service,MY_EMAIL,creds)
            if result.get("status") == "error":
                failed_list.append({
                    "msg_id": result.get("msg_id"),
                    "reason": result.get("reason", "unknown_error"),
                })
            else:
                mark_email_as_processed(service, msg_id,label_name=None, also_mark_read=True)
            # End of for loop
        # === Update last_history_id.json ===
        if failed_list:
            try:
                all_failed = {item["msg_id"]: item for item in retry_failed + failed_list}
                merged_results = list(all_failed.values())
                # Write to failed_ids.json
                write_json(FAILED_FILE, merged_results)
#                with open(FAILED_FILE, "w", encoding="utf-8") as f:
#                    json.dump(merged_results, f, ensure_ascii=False, indent=2)
                logger.warning(f"⚠️ There are {len(failed_list)} messages failed,Wrote failed_ids.json {FAILED_FILE}")
            except Exception as e:
                logger.error(f"❌ Failed to write failed_ids.json: {e}")
        else:
            logger.info("✅ All messages processed successfully.")

        update_last_history_file(service)
        return ("", 204)
    except Exception as e:
        logger.exception("Webhook processing failed due to an exception")
        return ("", 204)
        #return jsonify({"error": str(e)}), 200  # return unfer webhook mode
        #return

"""
@app.route("/gmail-webhook", methods=["POST"])
def gmail_webhook():
    """
"""
Gmail Pub/Sub Push Trigger Entry.
Its only role is to trigger the execution of the existing logic; it does not perform any additional parsing.

    try:
        logger.info("📩 A Gmail Pub/Sub push notification has been received. Starting execution of the main logic....")
        result = main()  
        logger.info("✅ Email processing complete.")
        #return jsonify({"status": "ok"}), 200
        return ("", 204)

    except Exception as e:
        logger.exception("❌ webhook Exception occurred")
        #return jsonify({"error": str(e)}), 200
        return ("", 204)

"""
# -------------------------
# Run the app
# -------------------------

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    logger.info(f"Service started, listening on port  {port}")
    #  Built-in Flask (local) / gunicorn (Cloud Run)
    app.run(host="0.0.0.0", port=port)

"""
if __name__ == "__main__":
    logger.info("In local debug mode, the app handles Gmail messages directly (bypassing Pub/Sub).")
    main() 
"""
