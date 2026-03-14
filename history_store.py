import json
from datetime import datetime, timezone
from pathlib import Path

from aqt import mw

_HISTORY_FILE = "exam_simulator_history.json"
_SCHEMA_VERSION = 1


def _history_path() -> Path:
    return Path(mw.pm.profileFolder()) / _HISTORY_FILE


def _default_payload() -> dict:
    return {"version": _SCHEMA_VERSION, "entries": []}


def load_history() -> dict:
    path = _history_path()
    if not path.exists():
        return _default_payload()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _default_payload()
    if not isinstance(payload, dict):
        return _default_payload()
    if payload.get("version") != _SCHEMA_VERSION:
        return _default_payload()
    entries = payload.get("entries")
    if not isinstance(entries, list):
        payload["entries"] = []
    return payload


def save_history(payload: dict) -> None:
    path = _history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(path)


def record_simulation(exam_name: str, note_ids: list[int]) -> None:
    clean_name = (exam_name or "Unnamed_Exam").strip()
    unique_ids = sorted({int(nid) for nid in note_ids if nid is not None})
    if not unique_ids:
        return

    payload = load_history()
    payload.setdefault("entries", []).append({
        "exam_name": clean_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "note_ids": unique_ids,
    })
    save_history(payload)


def grouped_history() -> list[dict]:
    payload = load_history()
    grouped = {}
    for entry in payload.get("entries", []):
        exam_name = (entry.get("exam_name") or "Unnamed_Exam").strip()
        created_at = entry.get("created_at") or ""
        note_ids = {int(nid) for nid in entry.get("note_ids", [])}
        bucket = grouped.setdefault(exam_name, {
            "label": exam_name,
            "created_at": created_at,
            "note_ids": set(),
            "runs": 0,
        })
        bucket["note_ids"].update(note_ids)
        bucket["runs"] += 1
        if created_at and created_at > bucket["created_at"]:
            bucket["created_at"] = created_at

    result = []
    for exam_name, item in grouped.items():
        result.append({
            "label": exam_name,
            "created_at": item["created_at"],
            "note_ids": sorted(item["note_ids"]),
            "runs": item["runs"],
        })
    result.sort(key=lambda x: (x["created_at"], x["label"]), reverse=True)
    return result


def delete_history_labels(labels: list[str]) -> None:
    targets = {str(label).strip() for label in labels if str(label).strip()}
    if not targets:
        return
    payload = load_history()
    payload["entries"] = [
        entry for entry in payload.get("entries", [])
        if (entry.get("exam_name") or "Unnamed_Exam").strip() not in targets
    ]
    save_history(payload)


def clear_history() -> None:
    save_history(_default_payload())
