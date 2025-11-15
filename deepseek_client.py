import os
import json
import requests
import logging
import textwrap
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger("deepseek_client")

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "GEMINI").upper()  # GEMINI or DEEPSEEK
# Gemini (AI Studio)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")  # or gemini-1.5-flash

# DeepSeek (kept as fallback / optional)
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

import json
import re

def validate_and_parse_response(llm_response: str) -> dict:
    """Validate and prepare LLM response - improved version"""
    try:
        # Attempting first method: Attem to load json directly
        return json.loads(llm_response)
    except json.JSONDecodeError:
        try:
            # 
            # Interpret the content if failed to extract json directly
            start = llm_response.find('{')
            end = llm_response.rfind('}')
            
            if start != -1 and end != -1 and end > start:
                json_str = llm_response[start:end+1]
                return json.loads(json_str)
            else:
                return None
                
        except json.JSONDecodeError as e:
            return None

# Other way to interpret Json
def validate_and_parse_response_v2(llm_response: str) -> dict:
    """更健壮的JSON解析版本"""
    # Clean the response
    cleaned_response = llm_response.strip()
    
    # Attemp to interpret in diffrent way
    strategies = [
        # Exctra directly
        lambda: json.loads(cleaned_response),
        # Exctra the outer layer
        lambda: json.loads(re.search(r'\{[^{}]*\}', cleaned_response).group()),
        # 
        lambda: json.loads(re.search(r'\{.*\}', cleaned_response, re.DOTALL).group())
    ]
    
    for strategy in strategies:
        try:
            return strategy()
        except (json.JSONDecodeError, AttributeError):
            continue
    
    return {"error": "Could not parse valid JSON from response"}

# ========== Prompt builder (unchanged, already optimized) ==========
def build_schedule_prompt(email_body: str, baseline_date: str) -> str:
    """
    Prompt for LLM to extract confirmed meeting details from an email thread.
    Adds robust handling for:
      - Normalization of messy time expressions & spacing
      - Thread-aware confirmations
      - Counter-proposals (reply proposes a different time than offered)
      - Conflict detection
      - Cross-participant acceptance (Case 8 pattern)
      - Tolerant generic-acceptance parsing (typos like “the time is both work for me”)
    """
    prompt = (
f"Please analyze the following email THREAD and extract meeting details.\n\n"
f"THREAD (latest message first; quoted history may appear later):\n"
f"{email_body}\n\n"

f"Work strictly from the participants' actual conversation. Ignore any AI/system analysis blocks and UI boilerplate.\n"
f"Use {{baseline_date}} = {baseline_date} as the reference for resolving relative dates.\n\n"

f"Time & date normalization (apply BEFORE validation):\n"
f"- Accept and normalize mixed formats: '20:00 PM' → '20:00'; '8 pm' → '20:00'; '2025年11月4日' → '2025/11/04'.\n"
f"- Normalize extra/misplaced spaces in dates like '2025 /11/7' → '2025/11/07'.\n"
f"- Normalize separators to 'YYYY-MM-DD'.\n"
f"- If a short confirmation lacks a datetime (e.g., 'ok for me'), inherit the LAST explicitly proposed date+time above in the thread.\n"
f"- If only a date is proposed (no time), keep time unknown (do NOT invent a time).\n"
f"- If both 12h and 24h markers appear ('20:00 PM'), prefer 24h and drop AM/PM.\n"
f"- If AM/PM is missing in 12h times, infer only when unambiguous; otherwise leave unknown.\n\n"

f"Confirmation logic (thread-aware):\n"
f"CONFIRMED if and only if:\n"
f"1) Two or more different participants state the SAME specific date+time; or\n"
f"2) One participant proposes a specific date+time (or multiple options), and a different participant replies soon after with a clear acceptance "
f"   WITHOUT contradicting that option.\n"
f"   Short acceptances (case-insensitive; English/Chinese examples): "
f"'ok with me', 'works for me', 'the time is ok with me', 'sounds good', 'yes let's meet then', 'confirmed', "
f"'可以', '没问题', '可以的', '行', '好', '时间可以', '就这个时间', '那就这么定了'.\n"
f"In case (2), bind the acceptance to the LATEST unambiguous proposed datetime above. The accepter need not repeat the datetime.\n\n"

f"Generic acceptance (VERY IMPORTANT):\n"
f"- Treat phrases indicating acceptance of ANY/ALL options—despite grammar/typos—as generic acceptance of the offered choices. Examples include:\n"
f"  'both work', 'both works', 'both time(s) work', 'either works', 'either time is ok', 'any time works',\n"
f"  common typo variants like 'the time is both work for me', 'both are ok for me', 'ok to both', 'ok with both'.\n"
f"- When generic acceptance is present and the offer includes multiple specific candidate datetimes, "
f"  SELECT the **earliest FUTURE** candidate relative to {{baseline_date}} and mark as CONFIRMED.\n"
f"- Do NOT require the accepter to restate the exact datetime if their intent is clearly 'both/either/any'.\n\n"

f"Counter-proposals & conflicts:\n"
f"- If a reply proposes a DIFFERENT datetime than the offered options (even same date but different time), treat it as a COUNTER-PROPOSAL.\n"
f"- A counter-proposal requires explicit acceptance by another participant to be confirmed.\n"
f"- If one message offers MULTIPLE candidate times and no later message accepts ANY of them (neither a single explicit pick nor a generic acceptance), treat as NOT CONFIRMED.\n"
f"- Do NOT auto-select a time unless there is explicit generic/specific acceptance as above.\n\n"

f"Cross-participant acceptance (Case 8 refinement):\n"
f"- If participant A proposes a new specific datetime (counter-proposal), and a later message from participant B explicitly accepts the SAME datetime, treat this as CONFIRMED.\n"
f"- Example:\n"
f"  A: 'I'm not available then. My time is 2:00 PM 2025/11/7.'\n"
f"  B: 'The time is ok with me, 2:00 PM 2025/11/7.'\n"
f"  → Confirmed at 2025-11-07 14:00 (clarify_needed=false).\n\n"

f"When to mark clarification needed:\n"
f"- Multiple times proposed with no acceptance (neither a specific pick nor a valid generic acceptance); or\n"
f"- Counter-proposal exists without acceptance; or\n"
f"- Time cannot be normalized to a valid clock time/date; or\n"
f"- All candidate times are in the past relative to {{baseline_date}}.\n\n"

f"Validation (AFTER normalization):\n"
f"- Valid time: 00:00–23:59; dates must exist (no Feb 30, etc.).\n"
f"- Prefer confirmed FUTURE datetimes. If multiple confirmed future datetimes exist (rare), return the earliest confirmed one.\n\n"

f"Attendees & subject:\n"
f"- Collect all visible email addresses (From/To/Cc or in-body).\n"
f"- Infer meeting subject from the thread subject if possible; otherwise empty.\n\n"

f"Output (return ONLY valid JSON with these fields):\n"
f"- meeting_intent: true/false\n"
f"- meeting_subject: string (empty if unknown)\n"
f"- meeting_time: 'YYYY-MM-DD HH:MM' in 24h (omit timezone)\n"
f"- attendees: list of emails\n"
f"- confidence: high/medium/low\n"
f"- clarify_needed: true/false\n"
f"- clarify_reason: string (empty if none)\n"
f"- reasoning: brief explanation referencing the acceptance or conflict logic used\n\n"

f"Examples:\n"
f"A) Confirmation by short acceptance:\n"
f"   Offer: 'the time is 20:00 PM 2025/11/4' → normalize to '2025-11-04 20:00'.\n"
f"   Reply: 'the time is ok with me' → confirmed; clarify_needed=false.\n"
f"B) Counter-proposal needing clarification:\n"
f"   Offer: '10:00 AM 2025/11/5' OR '3:00 PM 2025/11/6'.\n"
f"   Reply: 'I am ok to talk at 11:00 AM 2025/11/5.' (different from offered 10:00 on 11/5) → COUNTER-PROPOSAL.\n"
f"   No later acceptance → clarify_needed=true; meeting_time=''.\n"
f"C) Cross-participant confirmed (Case 8):\n"
f"   A: 'My time is 2:00 PM 2025/11/7.'  B: 'The time is ok with me, 2:00 PM 2025/11/7.' → Confirmed at 2025-11-07 14:00.\n"
f"D) Generic acceptance with multiple options (THIS IS IMPORTANT):\n"
f"   Offer: '11:00 AM 2025/11/7 or 3:00 PM 2025/11/7'.\n"
f"   Reply: 'The time is both work for me' (typo but clear generic acceptance) → CONFIRMED at the earliest FUTURE option.\n\n"

f"All responses must be in English. Return ONLY the JSON."
    )
    return prompt




import google.generativeai as genai

import os
import json
from typing import Dict, Any
import logging # Added logging import for completeness

# Import all necessary libraries
import google.generativeai as genai
from google.api_core import exceptions as g_exceptions
# Import config type for better readability and type hinting
#from google.generativeai.types import GenerateContentConfig

# Assume GEMINI_API_KEY, GEMINI_MODEL, and logger are defined elsewhere.
# Note: In a real environment, you need to ensure these variables are accessible.
# Example Definitions for testing:
# GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
# logger = logging.getLogger(__name__)

from typing import Any, Optional, Tuple,Dict
import google.generativeai as genai
from google.api_core import exceptions as g_exceptions
from typing import Dict, Any
import os
from logger_config import logger
import os
import json

def parse_json_flex(s: Any) -> Tuple[Optional[dict], Optional[str]]:
    """
    Transfer json,string to Dict,return dict or None
    """
    # Return direclty if s is dict
    if isinstance(s, dict):
        return s, None

    # 2) Transfer s to string
    s = str(s).strip()
    if not s:
        return None, "empty input"

    # 3) Remove the JSON code block fences
    m = re.search(r"```json\s*([\s\S]*?)\s*```", s, re.IGNORECASE)
    if m:
        s = m.group(1).strip()

    # 4) If the outer layer is enclosed in single quotes and the inner content is a JSON string (containing \n, etc.), 
    #    first restore the inner string to its real form.
    #    For example ：'{"a": 1, "b": "x"}'  ->  {"a": 1, "b": "x"}
    if (s.startswith("'") and s.endswith("'")) or (s.startswith('"') and s.endswith('"')):
        try:
            # 
            s_unquoted = ast.literal_eval(s)
            # Transfer to Json form and read with json.loads
            return json.loads(s_unquoted), None
        except Exception as e:
            #  Adding other ways in here if falied to extraction 
            pass

    # 5) Load Directly
    try:
        return json.loads(s), None
    except json.JSONDecodeError:
        # 6) Extract the largest JSON block from the first { to the last } and try again (prevents truncation/extra characters before or after).
        start = s.find("{")
        end = s.rfind("}")
        if start != -1 and end != -1 and end > start:
            blob = s[start:end+1]
            try:
                return json.loads(blob), None
            except Exception as e:
                return None, f"json.loads failed after brace-trim: {e}"
        return None, "no JSON object could be decoded"

def extract_clean_json(ask_gemini_response: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Clean the response from gemini LLM and return dict
    """
    
     
    # 2. Get the original content
    raw_text = ask_gemini_response.get("content", "").strip()
    
    if not raw_text:
        print("❌ Falied to extract JSON: content is null.")
        return None
    match = re.search(r"```json\s*([\s\S]*?)\s*```", raw_text, re.DOTALL)
    
    if match:
        json_string = match.group(1).strip()
    else:
        json_string = raw_text

    # 4. Attempt to extract with json format directly
    try:
        parsed_data = json.loads(json_string) 
        print("✅ JSON extract success.")
        return parsed_data
    
    except json.JSONDecodeError as e:
        print(f"❌ Exctract Json Failed: Not an json format: {e}")
        # 打印部分内容帮助调试
        print(f"Part of the content: {json_string[:100]}...")
        return None

def ask_gemini(prompt: str, max_tokens: int = 2048) -> Dict[str, Any]:
    """
    Call Google Gemini via the official google-generativeai SDK
    using GenerativeModel (compatible with genai >=0.4, no Client required).
    
    Returns:
        {"status": "success", "content": "<text>"} or {"status": "error", "reason": "..."}
    """
    # 0) Check API KEY
    api_key = GEMINI_API_KEY
    if not api_key:
        return {"status": "error", "reason": "GEMINI_API_KEY not set"}

    # 1) Model option
    model_name = GEMINI_MODEL or "gemini-2.5-flash"

    try:
        # 2) Confgi SDK
        genai.configure(api_key=api_key)

        # 3) Create Instance
        model = genai.GenerativeModel(model_name)

        # 4) Create paramenter 
        generation_config = {
            "temperature": 0,
            "top_p": 0.9,
            "max_output_tokens": max_tokens,
            "response_mime_type": "application/json",
        }

        # 5) Call LLM 
        response = model.generate_content(prompt, generation_config=generation_config)
        if response.candidates and response.candidates[0].content.parts:
            result = getattr(response.candidates[0].content.parts[0], "text", "").strip()
        else:
            result = ""

      #  result = getattr(response.candidates[0].content.parts[0], "text", "").strip()
                            
        if not result:
            logger.debug(f"[Gemini raw] {response}")
            return {"status": "error", "reason": "gemini output error"}
        else:
            return {"status": "success", "content": result}

    except Exception as e:
        reason = str(e)
        if "NotFound" in reason or "404" in reason:
            return {"status": "error", "reason": f"gemini_model_not_found: {model_name}"}
        if "PermissionDenied" in reason or "403" in reason:
            return {"status": "error", "reason": "gemini_permission_denied (Invalid API Key/Service Not Enabled)"}
        if "ResourceExhausted" in reason or "429" in reason:
            return {"status": "error", "reason": "gemini_quota_exceeded"}

        return {"status": "error", "reason": f"gemini_call_failed: {reason}"}


def ask_deepseek(prompt: str, max_tokens: int = 800) -> Optional[str]:
    if not DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY not set in environment variables.")
        return None

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "As a meeting assistant, your task is to: analyze the email for scheduling intent, identify potential dates/times, and validate their accuracy."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        "max_tokens": max_tokens,
    }

    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()
        logger.debug(f"[DeepSeek raw] {content}")
        return content
    except Exception as e:
        logger.exception(f"[DeepSeek] Failed: {e}")
        return None

# -------------------------
# Parse the response from DeepSeek, preferentially extracting JSON from the text.
# -------------------------

import json
import re
import ast

def parse_llm_json(llm_text: str) -> dict | None:
    """
    Safely parses an LLM-outputted JSON string into a Python dictionary.

This function supports the following non-standard formats:

Strings wrapped in Markdown ```json code fences.

Extraneous whitespace and newlines.

Single quotes instead of double quotes.

Empty or non-JSON LLM output.

Returns:
A Python dictionary if parsing is successful, otherwise None.
    """
    if not llm_text:
        return None

    text = llm_text.strip()

    # Delete the  Markdown ```json 
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"```$", "", text)
    text = text.strip()

    if not text:
        return None

    # Attempt strict JSON parsing.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Attempt to parse by first replacing single quotes with double quotes.
    try:
        fixed_text = text.replace("'", '"')
        return json.loads(fixed_text)
    except json.JSONDecodeError:
        pass

    # Attempt to parse using ast.literal_eval (for safely evaluating Python literals).
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return None

import re
import html

_UI_NOISE_RE = re.compile(
    r"(?:\b上一封\b|\b下一封\b|\bOriginal Message\b|\b原始邮件\b)", re.IGNORECASE
)

import re

def _collapse_whitespace_keep_lines(s: str, max_blank_lines: int = 2) -> str:
    """
    Clean up unnecessary characters line by line (without changing line order):
    Compress consecutive spaces or tabs within each line into a single space.
    Remove leading and trailing whitespace from each line.
    Compress > 3 consecutive blank lines to at most max_blank_lines (default: 2).
    """
    lines = s.split("\n")
    out = []
    blank_run = 0

    for line in lines:
        # Multiple space/tab → unique space
        line = re.sub(r"[ \t]+", " ", line)
        # Remove the space at begin and end
        line = line.strip()

        if line == "":
            blank_run += 1
            if blank_run <= max_blank_lines:
                out.append("")
        else:
            blank_run = 0
            out.append(line)

    return "\n".join(out)


def safe_preprocess_email(text: str) -> str:
    if not text:
        return ""

    # 1) 
    s = html.unescape(text)
    s = s.replace("\r\n", "\n").replace("\r", "\n")

    # 2) Unicode 
    import unicodedata
    s = unicodedata.normalize("NFKC", s)

    # 3) Transfer the separator to space 
    #  
    trans = {ord(ch): 32 for ch in {chr(cp) for cp in range(0x110000)
                                    if unicodedata.category(chr(cp)).startswith("Z")}}
    trans.update({0xFEFF: None})  # 去掉 BOM
    s = s.translate(trans)

    # 
    s = re.sub(r"\bi\s*am\s*ok\s*(?:to|with)\s*both\b", "I am ok with both times", s, flags=re.IGNORECASE)
    s = re.sub(r"\bok\s*(?:to|with|for)\s*both\b", "ok with both times", s, flags=re.IGNORECASE)
    s = re.sub(r"\bok\s*to\s*both\s*time(s)?\b", "ok with both times", s, flags=re.IGNORECASE)
    s = re.sub(r"\bi\s*am\s*ok\s*to\s*both\s*time(s)?\b", "I am ok with both times", s, flags=re.IGNORECASE)
    s = re.sub(r"\bboth\s*time\b", "both times", s, flags=re.IGNORECASE)


    # 5) Regulate the data/time format
    s = re.sub(r"(\b\d{1,2}:\d{2}\b)\s*(am|pm)\b", lambda m: f"{m.group(1)} {m.group(2).upper()}",
               s, flags=re.IGNORECASE)
    s = re.sub(r"\b(\d{4})([/-])(\d{1,2})([/-])(\d{1,2})\b",
               lambda m: f"{m.group(1)}{m.group(2)}{m.group(3).zfill(2)}{m.group(4)}{m.group(5).zfill(2)}",
               s)

    # 6) 
    s = _collapse_whitespace_keep_lines(s)
    return s.strip()



import re
import json

def preprocess_email_content(email_body: str) -> str:
    """
   Preprocess the email content to extract key information.
    """
    # Clean up excessive line breaks and whitespace.
    cleaned_body = re.sub(r'\n{3,}', '\n\n', email_body.strip())
    
# Extract the key conversational part (adjustable based on actual email format)
# Here we assume important info is at the beginning or contains time expressions
    lines = cleaned_body.split('\n')
    important_lines = []
    
# Retain lines containing: time expressions, confirmation phrases, or email addresses.
    time_patterns = [r'\d{4}[-/]\d{1,2}[-/]\d{1,2}', r'\d{1,2}:\d{2}', r'AM|PM', r'上午|下午']
    confirm_patterns = [r'good to', r'confirm', r'agree', r'ok with', r'works for', r'同意', r'确认']
    
    for line in lines:
        line_lower = line.lower()
# Consider a line important if it contains time information or confirmation cues.
        if any(re.search(pattern, line_lower) for pattern in time_patterns + confirm_patterns):
            important_lines.append(line)
# ...or contains an email address.
        elif re.search(r'[\w\.-]+@[\w\.-]+\.\w+', line):
            important_lines.append(line)
    
    if important_lines:
        return '\n'.join(important_lines)
    else:
        return cleaned_body


from datetime import datetime

def post_process_analysis(result: dict, original_email: str, baseline_date: str = None) -> dict:
    """
    Post-process the analysis results to perform logical verification and correction.
    Check for clear confirmation statements that were incorrectly flagged as requiring clarification.
    Also revalidate that the meeting time is not in the past.
    """

    confirm_phrases = [
        "good to talk at", "confirmed", "agree", "works for me", 
        "ok with", "i am good", "sounds good"
    ]

    has_confirmation = any(phrase in original_email.lower() for phrase in confirm_phrases)

    # 
    if has_confirmation and result.get("clarify_needed"):
        ...

    # Valid the data/time 
    try:
        meeting_time = result.get("meeting_time")
        if meeting_time and baseline_date:
            mt = datetime.strptime(meeting_time, "%Y-%m-%d %H:%M")
            bd = datetime.strptime(baseline_date, "%Y/%m/%d")
            if mt < bd:
                result["clarify_needed"] = True
                result["clarify_reason"] = (
                    f"The proposed meeting time ({meeting_time}) is earlier than the reference date ({baseline_date})."
                )
                result["confidence"] = "low"
    except Exception as e:
        result.setdefault("clarify_reason", f"Time validation error: {e}")
        result["clarify_needed"] = True

    return result

def analyze_meeting_schedule(email_body: str, baseline_date: str = "") -> dict:
    """
End-to-End Meeting Time Analysis Pipeline
    """
    try:
        if not baseline_date:
            baseline_date = datetime.now().strftime("%Y/%m/%d")
        # 1.Pre
        processed_email = safe_preprocess_email(email_body)
        #processed_email = preprocess_email_content(email_body)
        print("The contant of email after preprocess:")
        print(processed_email)
        print("-" * 50)
        
        # 2.Construct prompt and call DeepSeek
        prompt = build_schedule_prompt(processed_email, baseline_date)
        if LLM_PROVIDER == "GEMINI":
            llm_response = ask_gemini(prompt,max_tokens=4096)
        else:
            llm_response = ask_deepseek(prompt,max_tokens=4096)
        print("LLM Response:")
        print(llm_response)
        print("-" * 50)
        if llm_response["status"] == "error":
            return {
                "status": "error",            # ✅ system error
                "meeting_intent": None,       # 
                "meeting_time": "",
                "attendees": [],
                "confidence": "low",
                "clarify_needed": True,
                "clarify_reason": "LLM call failed",
                "reasoning": llm_response["content"],  # reason for failure
            }
        
        # 3. Parse LLM response
        result = validate_and_parse_response(llm_response["content"])
        if result == None:
            return {
                    "status": "error",            # ✅ system error
                    "meeting_intent": None,       # 
                    "meeting_time": "",
                    "attendees": [],
                    "confidence": "low",
                    "clarify_needed": True,
                    "clarify_reason": "LLM call failed",
                    "reasoning": "Json format failed"  # reason for failure
            }
        
        # 4. Post
        result = post_process_analysis(result, email_body, baseline_date)
        result["status"] = "ok"        
        return result
        
    except Exception as e:
        return {
            "status":"error",
            "meeting_intent": False,
            "meeting_time": "",
            "attendees": [],
            "confidence": "low", 
            "clarify_needed": True,
            "clarify_reason": f"LLM processing failed: {str(e)}",
            "reasoning": "System error during processing."
        }

# Sam
if __name__ == "__main__":
    email_content = """Email content here..."""
    
    result = analyze_meeting_schedule(email_content)
    print("Final Result:")
    print(json.dumps(result, indent=2, ensure_ascii=False))


import json
import re

def validate_and_parse_response(llm_response: str) -> dict:
    """validate and prepare LLM response"""

    try:
        # Extract JSON object from the response text
        json_match = re.search(r'\{.*\}', llm_response, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        else:
            return {"error": "No valid JSON found in response"}
    except json.JSONDecodeError:
        return {"error": "Invalid JSON format"}