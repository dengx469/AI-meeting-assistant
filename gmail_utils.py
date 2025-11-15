from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from bs4 import BeautifulSoup
import base64, json, os
from logger_config import logger
from typing import Dict, Any, List, Optional
from email.mime.text import MIMEText
import config_bucket as config
from googleapiclient.errors import HttpError
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send"
]

MAX_RESULTS = int(os.getenv("MAX_FETCH", "10"))
TOKEN_FILE = os.getenv("GMAIL_TOKEN_FILE", "token.json")
MY_EMAIL = os.getenv("GMAIL_SENDER", "dengxiao910@gmail.com").lower()
CLIENT_ID = config.CLIENT_ID
CLIENT_SECRET = config.CLIENT_SECRET
REFRESH_TOKEN = config.REFRESH_TOKEN

MEETING_LABEL_NAME = "MEETING_PROCESSED"

def get_or_create_label(service, label_name: str) -> str:
    """Return labelId for label_name; create it if missing."""
    try:
        resp = service.users().labels().list(userId="me").execute()
        for lbl in resp.get("labels", []):
            if lbl.get("name") == label_name:
                return lbl["id"]
        # create if not found
        body = {
            "name": label_name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show"
        }
        created = service.users().labels().create(userId="me", body=body).execute()
        return created["id"]
    except HttpError as e:
        logger.error(f"Failed to get/create label '{label_name}': {e}")
        raise

def mark_email_as_processed(service, msg_id: str,  label_name: Optional[str] = None, also_mark_read: bool = False) -> bool:
    """
    Add MEETING_PROCESSED label;optionally mark as read.
    Gmail scope: https://www.googleapis.com/auth/gmail.modify
    """
    try:
        final_label = (label_name or MEETING_LABEL_NAME or os.getenv("MEETING_LABEL_NAME") or "MEETING_PROCESSED").strip()
        if not final_label:
            final_label = "MEETING_PROCESSED"
            

        logger.debug(f"mark_email_as_processed: using label_name='{final_label}'")
        label_id = get_or_create_label(service, final_label)
        body = {"addLabelIds": [label_id]}
        if also_mark_read:
            body.setdefault("removeLabelIds", []).append("UNREAD")

        service.users().messages().modify(
            userId="me",
            id=msg_id,
            body=body
        ).execute()
        logger.info(f"✅ Email {msg_id} labeled as {final_label}"
                    + (" and marked read." if also_mark_read else "."))
        return True
    except HttpError as e:
        logger.warning(f"⚠️ Label email {msg_id} as {final_label} failed: {e}")
        return False
    except Exception as e:
        logger.exception(f"Unexpected error labeling email {msg_id}: {e}")
        return False



def mark_email_as_read(service, msg_id: str) -> bool:
    """
    
    
    :param service: Gmail API service instance
    :param msg_id: Email ID
    :return: Return True if success, else return False
    """
    try:
        # Mark the email as read by removing the UNREAD label
        service.users().messages().modify(
            userId="me",
            id=msg_id,
            body={"removeLabelIds": ["UNREAD"]}
        ).execute()
        logger.info(f"✅ Marked email {msg_id} as read.")
        return True
    except Exception as e:
        logger.warning(f"⚠️ Marked email {msg_id} as read failed: {e}")
        return False

def clean_to_header(to_value: str) -> str:
    """
    process 'Invalid To header', keep valid email addresses only
    """
    if not to_value:
        return ""
    addrs = []
    for part in to_value.split(","):
        addr = clean_email_address(part)
        if addr:
            addrs.append(addr.lower())
    addrs = list(dict.fromkeys(addrs))  
    return ", ".join(addrs)


from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import os
import logging

logger = logging.getLogger("gmail_helper")

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]

#!/usr/bin/env python3
# coding: utf-8

import os
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ================= CONFIG =================
# 
TOKEN_PATH = "/home/dengxiao910/token.json"

# API OAuth 
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/meetings.space.created",
]

# ==========================================



# Ensure the envirement values bellow was set in config.py
# CLIENT_ID = os.getenv("GMAIL_CLIENT_ID")
# CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET")
# REFRESH_TOKEN = os.getenv("GMAIL_REFRESH_TOKEN")

def get_credentials():
    """
    Access secret manager with CLIENT_ID, CLIENT_SECRET 和 REFRESH_TOKEN,
    Will refresh Access Token automatically
    """
    if not all([CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN]):
        # Falied to get mandate value
        raise ValueError(
            "❌ Falied to get mandate value：GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET 或 GMAIL_REFRESH_TOKEN."
            "pls check you config.py or env.yaml."
        )
    
    # 1. Create credentials object with access token.
    creds = Credentials(
        token=None,  
        refresh_token=REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        scopes=SCOPES
    )

    # 2. Refresh Access Token
    try:
        creds.refresh(Request())
    except Exception as e:
        # Failed to Refresh Token
        raise Exception(f"❌ Refresh Token invalid, create credentials again:{e}")

    if not creds.valid:
        raise Exception("❌ Failed to get Credentials, plese check Client/Secret/Refresh Token.")

    return creds

def get_gmail_service():
    """
    return Gmail service 和 credentials
    """
    creds = get_credentials()
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    logger = logging.getLogger("api_validator")

    try:
        profile = service.users().getProfile(userId='me').execute()
        # Attemp to access email with the service got. 
        logger.info(f"✅ Gmail Service Valid: {profile.get('emailAddress')}")
        return service,creds
    
    except HttpError as e:
        if e.resp.status in (401, 403):
        # 401 Unauthorized or 403 Forbidden
            logger.error(f"❌ Gmail Service invalid:Access Token expired or invalid。HTTP code: {e.resp.status}")
        else:
        # Other API error
            logger.error(f"❌ Gmail Service API error:{e}")
        return False
    
    except Exception as e:
        logger.exception(f"❌ Gmail Service Falied:{e}")
        return False
    return service, creds

def get_calendar_service():
    """
    Return calendar service and credentials
    """
    creds = get_credentials()
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    return service, creds



def extract_text_from_payload(payload: Dict[str, Any]) -> str:
    parts_text: List[str] = []

    def walk(part: Dict[str, Any]):
        mime_type = part.get("mimeType", "")
        body = part.get("body", {})
        # text/plain
        if mime_type == "text/plain" and "data" in body:
            try:
                raw = body.get("data", "")
                text = base64.urlsafe_b64decode(raw).decode("utf-8", errors="ignore")
                parts_text.append(text)
            except Exception as e:
                logger.warning(f"[decode text/plain] Failed: {e}")
        # text/html
        elif mime_type == "text/html" and "data" in body:
            try:
                raw = body.get("data", "")
                html = base64.urlsafe_b64decode(raw).decode("utf-8", errors="ignore")
                text = BeautifulSoup(html, "html.parser").get_text(separator="\n")
                parts_text.append(text)
            except Exception as e:
                logger.warning(f"[decode text/html] Failed: {e}")
        # multipart: 递归
        elif "parts" in part:
            for sub in part.get("parts", []):
                walk(sub)
        #
        elif mime_type == "" and "data" in body:
            try:
                raw = body.get("data", "")
                text = base64.urlsafe_b64decode(raw).decode("utf-8", errors="ignore")
                parts_text.append(text)
            except Exception:
                pass

    walk(payload)
    # 
    if not parts_text:
        return ""
    combined = "\n\n".join(p.strip() for p in parts_text if p and p.strip())
    return combined.strip()

def send_reply(service, thread_id, to, subject, body,msg_id=None):
    msg = MIMEText(body, "plain", "utf-8")
    # 统一清洗 To
    to_clean = clean_to_header(to)
    if not to_clean:
        # give up if no valid recipient
        logger.warning("send_reply: Cancelled if receiver is null.")
        return False
    
    recipients = [e.strip() for e in to_clean.split(",") if e.strip()]
    recipients = [r for r in recipients if r.lower() != MY_EMAIL]
    if not recipients:
        logger.info("📭 Return if no recepients.")
        return False
    msg["To"] = to_clean
    msg["Subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    try:
        # === 发送回复 ===
        service.users().messages().send(
            userId="me",
            body={"raw": raw, "threadId": thread_id}
        ).execute()
        logger.info(f"📤 Replied {thread_id} -> {to_clean}")

        
        return True

    except Exception as e:
        logger.error(f"❌ Failed to send reply: {e}")
        return False

import re

def clean_email_address(addr: str):
    """Extract clean email address, e.g. 'Peter <someone@gmail.com>' -> 'someone@gmail.com'"""
    if not addr:
        return None
    match = re.search(r'[\w\.-]+@[\w\.-]+', addr)
    return match.group(0) if match else None

    """
    Fetch latest messages from Gmail. list -> get,
    Extract the message after timestamp if specified.
    """
"""
def fetch_latest_messages(service, after_timestamp: int = None, max_results: int = MAX_RESULTS) -> List[Dict[str, Any]]:

    q_parts = ["label:inbox", "is:unread", "(subject:confirmation OR subject:confirm)"]
    if after_timestamp:
        q_parts.append(f"after:{after_timestamp}")
    query = " ".join(q_parts)

    resp = service.users().messages().list(
        userId="me",
        q=query,
        maxResults=max_results
    ).execute()

    msgs = resp.get("messages", []) or []
    results = []
    for m in msgs:
        try:
            msg = service.users().messages().get(userId="me", id=m["id"], format="full").execute()
            results.append(msg)
        except Exception:
            logger.exception(f"Get message {m.get('id')} Failed")
    results.sort(key=lambda x: int(x.get("internalDate", "0")), reverse=True)
    return results
"""
from typing import Dict, Any, List, Optional

def fetch_latest_messages(
    service,
    after_timestamp: Optional[int] = None,
    max_results: int = MAX_RESULTS
) -> List[Dict[str, Any]]:
    """
    Extract the unread email messages from Gmail
    Rules:
    Only search INBOX
    Only search unread emails (is:unread)
    Only search for subjects containing confirmation/confirm
    If after_timestamp is provided, use Gmail's after:<unix_ts> for incremental time filtering

    after_timestamp must be a "Unix timestamp in seconds (UTC)"

    Recommended to use internalDate from previously processed emails in the last round (milliseconds → seconds)
    Do not mark as read here; the marking logic should be handled by the caller.
    """

    q_parts = [
        "label:inbox",
        "is:unread",
        "(subject:confirmation OR subject:confirm)"
    ]

    if after_timestamp:
        # Gmail after: 
        q_parts.append(f"after:{int(after_timestamp)}")

    q = " ".join(q_parts)

    try:
        resp = service.users().messages().list(
            userId="me",
            labelIds=["INBOX"], 
            maxResults=max_results,
            q=q
        ).execute()
    except Exception as e:
        logger.error(f"Failed to fetch latest messages: {e}")
        return []

    msgs = resp.get("messages", []) or []
    results: List[Dict[str, Any]] = []

    # Extract the email body
    for m in msgs:
        try:
            msg = service.users().messages().get(
                userId="me",
                id=m["id"],
                format="full"
            ).execute()
            results.append(msg)
        except Exception as e:
            logger.warning(f"Failed to fetch message {m.get('id')}: {e}")

    # Sort by time.
    results.sort(key=lambda x: int(x.get("internalDate", "0")), reverse=True)
    return results

import time
import googleapiclient.errors
def with_backoff(fn, *args, **kwargs):
    
    delay = 1.0
    for i in range(6):
        try:
            return fn(*args, **kwargs).execute()
        except googleapiclient.errors.HttpError as e:
            status = getattr(e, "status_code", None) or getattr(e.resp, "status", None)
            msg = str(e)
            if status in (403, 429, 500, 503) or "quotaExceeded" in msg:
                logger.warning(f"Handle API rate limiting and exceptions(Attempt {i+1}):{msg},{delay:.1f}s retry")
                time.sleep(delay)
                delay *= 2
                continue
            raise
        except Exception:
            raise