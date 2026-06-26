import json
from pathlib import Path

from aqt import mw

_PRESETS_FILE = "exam_simulator_presets.json"
_SCHEMA_VERSION = 1


def _presets_path() -> Path:
    return Path(mw.pm.profileFolder()) / _PRESETS_FILE


def _default_payload() -> dict:
    return {"version": _SCHEMA_VERSION, "presets": []}


def load_presets() -> list[dict]:
    path = _presets_path()
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, dict) or payload.get("version") != _SCHEMA_VERSION:
        return []
    presets = payload.get("presets", [])
    if not isinstance(presets, list):
        return []
    clean = []
    for preset in presets:
        name = str(preset.get("name", "")).strip()
        rules = preset.get("rules", [])
        if not name or not isinstance(rules, list):
            continue
        clean_rules = []
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            tag = str(rule.get("tag", "")).strip()
            try:
                count = int(rule.get("count", 0))
            except Exception:
                count = 0
            if tag and count > 0:
                clean_rules.append({"tag": tag, "count": count})
        if clean_rules:
            clean.append({"name": name, "rules": clean_rules})
    return clean


def save_presets(presets: list[dict]) -> None:
    path = _presets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(
            {"version": _SCHEMA_VERSION, "presets": presets},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    tmp_path.replace(path)


def upsert_preset(name: str, rules: list[tuple[str, int]]) -> None:
    clean_name = str(name).strip()
    clean_rules = [
        {"tag": str(tag).strip(), "count": int(count)}
        for tag, count in rules
        if str(tag).strip() and int(count) > 0
    ]
    if not clean_name or not clean_rules:
        return
    presets = [
        preset for preset in load_presets()
        if preset["name"] != clean_name
    ]
    presets.append({"name": clean_name, "rules": clean_rules})
    presets.sort(key=lambda item: item["name"].lower())
    save_presets(presets)


def delete_preset(name: str) -> None:
    target = str(name).strip()
    if not target:
        return
    save_presets([
        preset for preset in load_presets()
        if preset["name"] != target
    ])
