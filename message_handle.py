
import logging
import os
from datetime import datetime
from deepseek_client import analyze_meeting_schedule
from gmail_utils import clean_email_address,extract_text_from_payload,send_reply
from logger_config import logger
from time_parser import parse_human_time,get_sender_timezone
from calendar_utils import create_calendar_event,send_meeting_invite
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from update_mail_history import record_failed_event,ensure_failed_file_exists
import config_bucket as config


TOKEN_FILE = config.TOKEN_FILE
TOKEN_JSON_ENV = os.getenv("GMAIL_TOKEN_JSON") or os.getenv("TOKEN_JSON")  
DEFAULT_TZ = os.getenv("DEFAULT_TZ", "Asia/Shanghai")
SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",  # Update labels
    "https://www.googleapis.com/auth/gmail.labels",  # Create labels
    "https://www.googleapis.com/auth/calendar"
]
SEND_MEETING_INVITE = os.getenv("SEND_MEETING_INVITE", "0") == "1"

def _normalize_text(s: str | None) -> str:
    s = (s or "").replace("\r\n", "\n").replace("\r", "\n")
    # 压缩过多空行
    while "\n\n\n" in s:
        s = s.replace("\n\n\n", "\n\n")
    return s.strip()

def _truncate(s: str, limit: int = 8000) -> str:
    return s if len(s) <= limit else s[:limit] + "\n...[truncated]"

def _compose_clarify_reply(subject: str, email_body: str, reason: str) -> tuple[str, str]:
    """返回 (reply_text, reply_html)；如果不发 HTML，可忽略 html 返回值。"""
    import html
    safe_subject = _normalize_text(subject)
    safe_body = _truncate(_normalize_text(email_body or ""))
    safe_reason = reason or "unspecified"

    reply_text = (
        "Dear Attendees,\n\n"
        "We received your meeting thread, but we could not determine a single confirmed meeting time.\n"
        f"Reason from System Alert: {safe_reason}\n\n"
        "Please see the original email content below:\n"
        "----------------------------------------\n"
        f"Subject: {safe_subject}\n\n"
        "Body:\n"
        f"{safe_body}\n"
        "----------------------------------------\n"
        "Thanks!\n— Automated conference assistant"
    )

    reply_html = f"""
<p>Dear Attendees,</p>
<p>We received your meeting thread, but we could not determine a single confirmed meeting time.<br/>
Reason from System Alert: {html.escape(safe_reason)}</p>
<p>Please see the original email content below:</p>
<hr/>
<p><strong>Subject:</strong> {html.escape(safe_subject)}</p>
<p><strong>Body:</strong><br/>
<pre style="white-space:pre-wrap;">{html.escape(safe_body)}</pre></p>
<hr/>
<p>Thanks!<br/>— Automated conference assistant</p>
""".strip()

    return reply_text, reply_html

def process_single_message(msg: dict, service, my_email,creds):
    """Process a single Gmail message: analyze, clarify, create calendar event"""
    msg_id = msg.get("id")
    thread_id = msg.get("threadId")
    internal_date = msg.get("internalDate")

    logger.info(f"--- Processing id={msg_id}, thread={thread_id}, internalDate={internal_date}")

    try:
        # ---- 1) Extract headers ----
        payload = msg.get("payload", {}) or {}
        headers = {h.get("name", ""): h.get("value", "") for h in payload.get("headers", [])}
        subject = headers.get("Subject", "") or ""
        sender = headers.get("From", "") or ""
        to_field = headers.get("To", "") or ""
        cc_field = headers.get("Cc", "") or ""
        logger.info(f"Email From={sender}; To={to_field}; Cc={cc_field}; Subject={subject}")

        # ---- 2) Extract body ----
        body = extract_text_from_payload(payload)
        if not body or not body.strip():
            logger.warning("Message empty or only whitespace. Skipping.")
            return {"status": "skipped", "reason": "empty_body", "msg_id": msg_id}

        # Double Check,Ensure subject contains 'confirm' or 'confirmation'
        subj_lower = subject.lower()
        if not any(k in subj_lower for k in ("confirm", "confirmation")):
            logger.info("Subject doesn't contain 'confirm' or 'confirmation'. Skipping.")
            return {"status": "skipped", "reason": "no_confirmation_keyword", "msg_id": msg_id}

        # ---- 3) Extract date ----
        try:
            sent_ts = int(internal_date or 0) / 1000
            sent_dt = datetime.fromtimestamp(sent_ts)
            baseline_date = sent_dt.strftime("%Y/%m/%d")
        except Exception:
            sent_dt = datetime.now()
            sent_ts = sent_dt.timestamp()
            baseline_date = sent_dt.strftime("%Y/%m/%d")

        # ---- 4) Call LLM ----
        result = analyze_meeting_schedule(body, baseline_date)
        if not result:
            logger.error("Failed to call LLM. Skipping.")
            return {"status": "error", "reason": "llm_failed", "msg_id": msg_id}

        status = result.get("status")
        if status == "error":
            # Error when calling LLM
            return {"status": "error", "reason": result.get("reason", "llm_error"), "msg_id": msg_id}

        meeting_intent = result.get("meeting_intent")
        free_time = (result.get("meeting_time") or "").strip()
        clarify_needed = bool(result.get("clarify_needed", False))
        clarify_reason = result.get("clarify_reason", "")

        # ---- 5) Clarify
        if clarify_needed or not meeting_intent:
            # 汇总收件人：To/Cc/LLM抽取/From
            recipients = set()
            for field in (to_field, cc_field):
                for part in (field or "").split(","):
                    e = clean_email_address(part)
                    if e:
                        recipients.add(e.lower())

            sender_clean = clean_email_address(sender)
            if sender_clean:
                recipients.add(sender_clean.lower())

            for e in (result.get("attendees") or []):
                ce = clean_email_address(e)
                if ce:
                    recipients.add(ce.lower())

            # Remove self email
            if my_email and my_email.lower() in recipients:
                recipients.discard(my_email.lower())

            # If no recipients, add sender
            if not recipients and sender_clean:
                recipients.add(sender_clean.lower())

            all_to = ", ".join(sorted(recipients)) if recipients else (sender_clean or "")
            reply_subject = f"Please clarify meeting time - {subject or 'Meeting Confirmation'}"

            default_reason = "We couldn't find a clear single meeting time in your message."
            reason = clarify_reason or default_reason
            reply_text, reply_html = _compose_clarify_reply(subject, body, reason)

            # Send clarification email
            send_reply(service, thread_id, all_to, reply_subject, reply_text, msg_id=msg_id)
            logger.info("Clarification email sent, skip follow-up processing")
            return {"status": "Clarify", "reason": clarify_reason or "need_clarification", "msg_id": msg_id}

        # ---- 6) Create Calendar Event ----
        dt_obj = None
        if free_time:
            try:
                # "YYYY-MM-DD HH:MM" or with seconds
                dt_obj = datetime.fromisoformat(free_time)
            except Exception:
                try:
                    dt_obj = parse_human_time(free_time, base_dt=sent_ts)
                except Exception:
                    dt_obj = None

        if not dt_obj:
            # Invalid time
            reply_subject = f"Please confirm the meeting time — {subject}" if subject else "Please confirm the meeting time"
            fmt_hint = "Please reply with a confirmation in a format such as '2025-11-05 11:00' or 'next Tuesday at 5pm'. Thank you!"
            reply_text, reply_html = _compose_clarify_reply(subject, body, f"invalid or unparsable time. {fmt_hint}")
            # Send clarification email
            to_addr = clean_email_address(sender) or sender
            send_reply(service, thread_id, to_addr, reply_subject, reply_text, msg_id=msg_id)
            logger.info("Clarification email (invalid time) sent, skip follow-up processing")
            return {"status": "Clarify", "reason": "invalid_time", "msg_id": msg_id}

        # ---- 7) Extract Attendees ----
        participants = set()
        for field in (to_field, cc_field):
            for part in (field or "").split(","):
                e = clean_email_address(part)
                if e and e.lower() != (my_email or "").lower():
                    participants.add(e.lower())

        # Add attendees
        for part in (result.get("attendees") or []):
            e = clean_email_address(part)
            if e and e.lower() != (my_email or "").lower():
                participants.add(e.lower())

        sender_clean = clean_email_address(sender)
        if sender_clean and sender_clean.lower() != (my_email or "").lower():
            participants.add(sender_clean.lower())

        attendees = sorted(participants) or ([sender_clean.lower()] if sender_clean else [])

        # ---- 8) Initialize Calendar Service ----
        try:
            calendar_service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        except Exception as e:
            logger.error(f"Failed to initialize Google Calendar service: {e}")
            return {"status": "error", "reason": "calendar_service_init_failed", "msg_id": msg_id}

        # ---- 9) Create Calendar Event ----
        tz_name = get_sender_timezone(headers, DEFAULT_TZ)
        event_summary = subject or "meeting"

        evt = create_calendar_event(
            creds=creds,
            service_gmail=service,
            thread_id=thread_id,
            sender=sender,
            subject=subject,
            summary=event_summary,
            start_time=free_time,   # "YYYY-MM-DD HH:MM"
            attendees_emails=attendees,
            tz_name=tz_name,
            msg_id=msg_id
        )

        if evt:
            meet_link = evt.get("hangoutLink") or evt.get("conferenceData", {}).get("entryPoints", [{}])[0].get("uri")
            if meet_link and SEND_MEETING_INVITE:
                # Send meeting invite
                to_for_invite = ", ".join(attendees)
                send_meeting_invite(service, thread_id, to_for_invite,
                                    f"Meeting Confirmation: {event_summary}", meet_link, free_time, msg_id=msg_id)
            logger.info(f"✅ Successfully created event for message {msg_id}")
            return {
                "status": "success",
                "msg_id": msg_id,
                "event_id": evt.get("id"),
                "summary": event_summary,
                "meeting_time": free_time,
                "attendees": attendees,
                "meet_link": meet_link,
            }

        logger.warning("Failed to create calendar event.")
        return {"status": "error", "reason": "create_event_failed", "msg_id": msg_id}

    except Exception as e:
        logger.exception(f"Failed to process message {msg_id}")
        # record_failed_event(service, msg_id, f"process_message: {e}")
        return {"status": "error", "reason": f"process_message: {e}", "msg_id": msg_id}


def process_messages(msg_list: list, service,my_email,creds):
    """Process a batch of Gmail messages"""
    # First process failed messages from previous runs
    failed_data = ensure_failed_file_exists(service)  # now returns dict
    for failed_id, info in failed_data.items():
        try:
            # Fetch the message by ID and process it again
            msg = service.users().messages().get(userId="me", id=failed_id).execute()
            process_single_message(msg, service,creds)
        except Exception as e:
            logger.error(f"Failed to reprocess failed message {failed_id}: {e}")

    # Now process the new batch
    for msg in msg_list:
        process_single_message(msg, service)