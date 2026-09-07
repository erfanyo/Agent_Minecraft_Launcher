"""Shared redaction for display, feedback and AI audit logs (never execution data)."""
import re
import json

MASK = "[REDACTED]"
_KEY = re.compile(r"token|api[_-]?key|password|secret|authorization|credential|auth_session", re.I)
_PAIR = re.compile(r'''(?i)((?:["']?)(?:[\w.-]*(?:token|api[_-]?key|password|secret|authorization|auth_session)[\w.-]*)(?:["']?)\s*[:=]\s*)("[^"\r\n]*"|'[^'\r\n]*'|[^\s,;}]+)''')
_CLI = re.compile(r'(?i)(--(?:accessToken|access_token|refresh_token|clientToken|session|password|api[_-]?key)(?:\s+|=))("[^"]*"|\S+)')

def sensitive_key(key):
    return bool(_KEY.search(str(key)))

def redact_text(text, settings=None):
    text = str(text or "")
    if text.lstrip().startswith(('{', '[')):
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            pass
        else:
            return json.dumps(redact(parsed, settings), ensure_ascii=False)
    # Exact secrets also cover unlabelled values in prose and error messages.
    def secrets(value, protected=False):
        if isinstance(value, dict):
            for key, child in value.items():
                yield from secrets(child, protected or sensitive_key(key))
        elif isinstance(value, (list, tuple)):
            for child in value:
                yield from secrets(child, protected)
        elif protected and isinstance(value, str) and len(value) >= 6:
            yield value
    for secret in sorted(set(secrets(settings or {})), key=len, reverse=True):
        text = text.replace(secret, MASK)
    text = re.sub(r'(?i)\bBearer\s+[^\s"\',;]+', 'Bearer ' + MASK, text)
    text = _CLI.sub(lambda m: m[1] + MASK, text)
    text = _PAIR.sub(lambda m: m[1] + '"' + MASK + '"', text)
    text = re.sub(r'\bsk-[A-Za-z0-9_-]{12,}\b', MASK, text)
    text = re.sub(r'(https?://)[^/\s:@]+:[^/\s@]+@', r'\1' + MASK + '@', text)
    text = re.sub(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', MASK, text)
    return text

def redact(value, settings=None, key=""):
    if sensitive_key(key):
        return MASK
    if isinstance(value, dict):
        # Tool set_setting encodes the sensitive name as a value, not a key.
        protected = sensitive_key(value.get("key", ""))
        return {str(k): MASK if protected and k in {"value", "old_value", "new_value"}
                else redact(v, settings, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, settings) for v in value]
    if isinstance(value, str):
        return redact_text(value, settings)
    return value
