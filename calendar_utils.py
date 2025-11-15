# -------------------------
# Created Calendar Event and Send Meeting Invite
# -------------------------

#import logging
import time,os
from datetime import timedelta
import dateparser
import pytz
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from logger_config import logger
from gmail_utils import send_reply,get_calendar_service
import hashlib
from googleapiclient.errors import HttpError


SEND_MEETING_REPLY = os.getenv("SEND_MEETING_REPLY", "0") == "1"

from googleapiclient.discovery import build
from datetime import timedelta
import time
import logging
import dateparser, pytz

logger = logging.getLogger("gmail_helper")
SEND_MEETING_REPLY = os.getenv("SEND_MEETING_REPLY", "0") == "1"

def create_calendar_event(
    creds,
    service_gmail,
    thread_id,
    subject,
    summary,
    start_time,
    attendees_emails,
    tz_name,
    sender=None,
    msg_id=None,
):
    logger.info(f"[CREATE_EVT] thread={thread_id}, msg={msg_id}, start={start_time}")
    try:
        # Extract credentials and calendar service
        service_calendar,creds = get_calendar_service()
        dt = dateparser.parse(start_time, settings={"RETURN_AS_TIMEZONE_AWARE": False})
        if not dt:
            body = (
                "We were unable to identify the meeting time.\n"
                "Please confirm by replying with a time like "
                "2025-10-22 15:00 or 3:00 PM next Wednesday. Thank you."
            )
            to_field = ",".join(attendees_emails)
            send_reply(
                service_gmail,
                thread_id,
                to_field,
                f"Please confirm the meeting time – {subject}",
                body,
                msg_id=msg_id,
            )
            return None

        tz = pytz.timezone(tz_name)
        dt_local = tz.localize(dt)
        end_dt_local = dt_local + timedelta(hours=1)

        raw_key = f"{thread_id}-{dt_local.isoformat()}".encode("utf-8")
        event_id = hashlib.md5(raw_key).hexdigest()[:20]

        event_body = {
            "id": event_id,
            "summary": summary,
            "start": {"dateTime": dt_local.isoformat(), "timeZone": tz_name},
            "end": {"dateTime": end_dt_local.isoformat(), "timeZone": tz_name},
            "conferenceData": {
                "createRequest": {"requestId": f"meet-{int(time.time())}"}
            },
            "attendees": [{"email": e} for e in attendees_emails],
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "email", "minutes": 30},
                    {"method": "popup", "minutes": 10},
                ],
            },
        }
        logger.info(
            f"[CREATE_EVT] thread={thread_id}, msg={msg_id}, "
            f"start={dt_local}, eventId={event_id}, attendees={attendees_emails}"
        )

        try:
            evt = (
                service_calendar.events()
                .insert(
                    calendarId="primary",
                    body=event_body,
                    conferenceDataVersion=1,
                    sendUpdates="all",
                    #eventId=event_id,
                )
                .execute()
            )
        except HttpError as e:
                # 409 = The event existed. 
                if e.resp.status == 409:
                    logger.info(
                    f"[IDEMPOTENT] Event already exists for eventId={event_id}, "
                    f"treat as success and skip duplicate."
                    )
                    return None
                logger.error(f"⚠️ Calendar API error: {e}")
                raise

        meet_link = (
            evt.get("hangoutLink")
            or evt.get("conferenceData", {}).get("entryPoints", [{}])[0].get("uri")
        )

        if meet_link:
            if SEND_MEETING_REPLY:
                body = (
                    f"Meeting Created:\n"
                    f"Subject: {summary}\n"
                    f"Time: {dt_local.strftime('%Y-%m-%d %H:%M')}\n"
                    f"Meet Link: {meet_link}"
                )
                send_reply(
                    service_gmail,
                    thread_id,
                    ", ".join(attendees_emails),
                    f"Meeting Created – {subject}",
                    body,
                    msg_id=msg_id,
                )
            else:
                logger.info("🟢 Calendar invitation sent, skip extra reply.")
        else:
            logger.warning("Meeting created, but failed to get meeting link.")

        return evt

    except Exception as e:
        logger.error(f"⚠️ Failed to create calendar event: {e}")
        if attendees_emails:
            try:
                send_reply(
                    service_gmail,
                    thread_id,
                    ", ".join(attendees_emails),
                    f"Failed to create calendar event – {subject}",
                    f"Detail: {e}",
                    msg_id=msg_id,
                )
            except Exception as mail_err:
                logger.error(f"⚠️ Also failed to send failure notice email: {mail_err}")
        return None



def send_meeting_invite(service_gmail, thread_id, to, subject, meet_link, start_time,msg_id=None):
    try:
        body_text = (
            f"Hello,\n\nMeeting Time:{start_time}\nLink:{meet_link}\n\n"
            "Plase Please arrive on time. If you need to make any modifications, please reply to this email.\n\n-- AI meeting assistant"
            
        )
        send_reply(service_gmail, thread_id, to, subject, body_text,msg_id=msg_id)
        logger.info(f"📧 Sent invitation  {to}")
    except Exception as e:
        logger.error(f"❌ Failed to send meeting invite:{e}")