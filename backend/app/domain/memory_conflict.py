import json
import re
from enum import StrEnum
from hashlib import sha256

_AGE = re.compile(r"^\d+岁$")


class ConflictStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class ConflictResolution(StrEnum):
    KEEP_EXISTING = "keep_existing"
    ACCEPT_INCOMING = "accept_incoming"
    EDIT = "edit"
    DISMISS = "dismiss"


def contradiction_category(kind: str, fact_key: str, current: dict, incoming: dict) -> str | None:
    """Return a conflict category only for an explicit contradiction."""

    current_value = current.get("value")
    incoming_value = incoming.get("value")
    if (
        fact_key == "identity"
        and isinstance(current_value, str)
        and isinstance(incoming_value, str)
        and _AGE.fullmatch(current_value)
        and _AGE.fullmatch(incoming_value)
    ):
        return "age"
    if kind == "world_fact" and fact_key == "description":
        return "location"
    if kind == "world_fact" and fact_key == "statement":
        return "world_rule"
    return None


def value_fingerprint(value: dict) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode()).hexdigest()


def split_rule(text: str) -> tuple[str, str | None]:
    """A rule topic is the text before the first full-width or ASCII colon."""

    cleaned = text.strip()
    for separator in ("：", ":"):
        if separator in cleaned:
            topic, statement = cleaned.split(separator, 1)
            topic = topic.strip()
            statement = statement.strip()
            if topic and statement:
                return topic, statement
    return cleaned, None
