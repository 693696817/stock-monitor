import datetime

_FEEDBACK_STATUS_MAP = {0: "pending", 1: "in_progress", 2: "done"}
_FEEDBACK_STATUS_REV = {"pending": 0, "in_progress": 1, "done": 2}

def _feedback_to_public(row):
    status_int = int(row.get("status") or 0)
    created = row.get("created_at")
    if isinstance(created, datetime.datetime):
        time_str = created.strftime("%Y-%m-%d %H:%M")
    else:
        time_str = str(created) if created else ""
    return {
        "id": row["id"],
        "type": (row.get("type") or "other"),
        "title": row.get("title") or "",
        "desc": row.get("content") or "",
        "status": _FEEDBACK_STATUS_MAP.get(status_int, "pending"),
        "votes": int(row.get("votes") or 0),
        "time": time_str,
    }
