#!/usr/bin/env python3
"""Soulbound DPS Meter — readable, dependency-free Python edition.

Requires Python 3.10+ with Tkinter (included with the normal Windows installer).
Combat logs are read only from the selected folder. No network access is used.
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import json
import os
import re
import shutil
import sys
import tempfile
import time
import tkinter as tk
from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any, Callable


VERSION = "0.8.14-py.1"
SUPPORTED_EXTENSIONS = {".jsonl", ".log", ".json", ".txt"}
SCRIPT_DIR = Path(__file__).resolve().parent
RECORDS_PATH = SCRIPT_DIR / "records.txt"
LOCAL_APP_DATA = Path(os.environ.get("LOCALAPPDATA", SCRIPT_DIR))
SETTINGS_PATH = LOCAL_APP_DATA / "SoulboundMeter" / "settings.json"
BRAND_ANIMATION_FRAME_COUNT = 30


def utc_now() -> float:
    return time.time()


def parse_timestamp(value: Any) -> float:
    if not value:
        return utc_now()
    try:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (TypeError, ValueError, OverflowError):
        return utc_now()


def timestamp_text(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")


def first_value(obj: Any, *names: str, default: Any = None) -> Any:
    if not isinstance(obj, dict):
        return default
    for name in names:
        if name in obj and obj[name] is not None:
            return obj[name]
    return default


def first_number(obj: Any, *names: str, default: float = 0.0) -> float:
    value = first_value(obj, *names, default=default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def first_bool(obj: Any, *names: str) -> bool:
    value = first_value(obj, *names, default=False)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"true", "yes", "1"}


def normalize_ability(name: str) -> str:
    return "".join(ch.lower() for ch in name if ch.isalnum())


def map_name_from_log_path(path: str) -> str:
    stem = Path(path).stem
    parts = stem.split("__")
    encoded = parts[1] if len(parts) > 1 and parts[1].strip() else stem
    words = [word for word in encoded.split("_") if word]
    return " ".join(words) if words else "Unknown map"


def is_unknown_ability(name: str | None) -> bool:
    return not name or name.strip().lower() in {"unknown", "unknown ability"}


def is_own_event(event: "CombatEvent") -> bool:
    if not event.source_type:
        return True
    return (
        event.source_type.lower() == "self"
        or (event.source_id or "").lower() == "self"
        or (event.source_name or "").lower() == "self"
    )


def format_number(value: float) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}m"
    if value >= 1_000:
        return f"{value / 1_000:.1f}k"
    return f"{value:.0f}"


def format_rate(value: float) -> str:
    text = f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{text}%"


def format_date(value: str | None) -> str:
    if not value:
        return "No record yet"
    try:
        dt = datetime.fromtimestamp(parse_timestamp(value)).astimezone()
        return f"{dt.strftime('%b')} {dt.day}, {dt.year}"
    except (ValueError, OSError):
        return "No record yet"


@dataclass(slots=True)
class CombatEvent:
    type: str
    event_id: str | None
    timestamp: float
    encounter_id: str | None
    source_id: str | None
    source_name: str | None
    source_type: str | None
    target_id: str | None
    target_name: str | None
    ability_id: str | None
    ability_name: str
    impact_type: str | None
    amount: float
    applied_amount: float
    raw_amount: float
    overheal: float
    absorbed: float
    critical: bool
    heavy_hit: bool
    periodic: bool
    sequence: float | None


def parse_combat_event(line_or_object: str | dict[str, Any]) -> CombatEvent | None:
    try:
        root = json.loads(line_or_object) if isinstance(line_or_object, str) else line_or_object
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(root, dict):
        return None

    raw_type = str(first_value(root, "type", "event_type", "event", default="")).strip().lower()
    if not raw_type:
        return None
    type_map = {
        "damage_dealt": "damage", "damaged": "damage", "hit": "damage",
        "healing_done": "heal", "healing_dealt": "heal", "heal_dealt": "heal",
        "heal_applied": "heal", "healing": "heal", "healed": "heal",
        "shield_gained": "shield", "run_start": "combat_start", "run_end": "combat_end",
    }
    event_type = type_map.get(raw_type, raw_type)
    payload = root.get("data") if isinstance(root.get("data"), dict) else root
    source = first_value(payload, "source", "actor", "caster", default={})
    target = first_value(payload, "target", "recipient", "victim", default={})
    if not isinstance(source, dict):
        source = {}
    if not isinstance(target, dict):
        target = {}

    if event_type == "damage":
        amount = first_number(payload, "post_target_mitigation_amount", "applied_amount", "effective_amount", "amount", "value")
        applied_amount = first_number(payload, "applied_amount", "effective_amount", "amount", "value", default=amount)
    else:
        amount = first_number(payload, "effective_amount", "applied_amount", "amount", "value")
        applied_amount = amount
    cast = payload.get("cast") if isinstance(payload.get("cast"), dict) else {}
    ability = payload.get("ability") if isinstance(payload.get("ability"), dict) else {}
    ability_name = first_value(payload, "ability_display_name", "ability_name", "skill_name", "action_name", "weapon_display_name")
    ability_name = ability_name or first_value(cast, "display_name") or first_value(ability, "name")
    ability_name = ability_name or first_value(payload, "ability_id", "skill_id", default="Unknown")
    impact_type_value = first_value(payload, "impact_type", "damage_type", "element_type")
    impact_type = str(impact_type_value).strip() if impact_type_value is not None else None
    impact_type = impact_type or None
    sequence_value = first_value(root, "sequence")
    try:
        sequence = float(sequence_value) if sequence_value is not None else None
    except (TypeError, ValueError):
        sequence = None

    return CombatEvent(
        event_type,
        str(first_value(payload, "event_id", "id", "sequence_id") or first_value(root, "event_id", "id", "sequence_id"))
        if (first_value(payload, "event_id", "id", "sequence_id") or first_value(root, "event_id", "id", "sequence_id")) is not None else None,
        parse_timestamp(first_value(root, "timestamp_utc", "timestamp", "time", "ts")),
        first_value(payload, "encounter_id", "combat_id", "session_id") or first_value(root, "encounter_id", "combat_id", "session_id"),
        first_value(source, "id", "entity_id", "user_id", "alias") or first_value(payload, "source_id", "actor_id"),
        first_value(source, "display_name", "name", "alias") or first_value(payload, "source_name", "actor_name"),
        first_value(source, "type"),
        first_value(target, "id", "entity_id", "user_id", "alias") or first_value(payload, "target_id", "victim_id"),
        first_value(target, "display_name", "name", "alias") or first_value(payload, "target_name", "victim_name"),
        first_value(payload, "ability_id", "skill_id", "action_id") or first_value(ability, "id"),
        str(ability_name),
        impact_type,
        max(0.0, amount),
        max(0.0, applied_amount),
        max(0.0, first_number(payload, "pre_target_mitigation_amount", "raw_amount", "unmitigated_amount", "raw_value", default=amount)),
        max(0.0, first_number(payload, "overheal", "overhealing")),
        max(0.0, first_number(payload, "absorbed", "blocked", "mitigated")),
        first_bool(payload, "is_crit", "critical", "crit", "is_critical"),
        first_bool(payload, "is_heavy_hit", "heavy_hit"),
        first_bool(payload, "periodic", "is_periodic", "dot", "hot"),
        sequence,
    )


def live_damage_event(event: CombatEvent, include_overkill: bool) -> CombatEvent:
    if event.type == "damage" and not include_overkill:
        return replace(event, amount=event.applied_amount)
    return event


class CombatAbilityResolver:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.healing_abilities: set[str] = set()
        self.shield_abilities: set[str] = set()
        self.last_healing_cast: tuple[str, float] | None = None
        self.last_shield_cast: tuple[str, float] | None = None

    def observe(self, root: dict[str, Any]) -> None:
        if str(root.get("event", "")).lower() != "loadout_snapshot":
            return
        abilities = root.get("data", {}).get("abilities", []) if isinstance(root.get("data"), dict) else []
        if not isinstance(abilities, list):
            return
        self.healing_abilities.clear()
        self.shield_abilities.clear()
        for ability in abilities:
            if not isinstance(ability, dict):
                continue
            name = str(ability.get("ability_display_name", "")).strip()
            lowered = name.lower()
            if name and "heal" in lowered:
                self.healing_abilities.add(name)
            if name and (lowered == "fortify" or "shield" in lowered or "barrier" in lowered):
                self.shield_abilities.add(name)

    def resolve(self, event: CombatEvent) -> CombatEvent:
        lowered = event.ability_name.lower()
        is_healing = event.ability_name in self.healing_abilities or "heal" in lowered
        is_shield = event.ability_name in self.shield_abilities or lowered == "fortify" or "shield" in lowered or "barrier" in lowered
        if event.type == "cast_result" and is_healing:
            self.last_healing_cast = (event.ability_name, event.timestamp)
            return event
        if event.type in {"cast_attempt", "cast_result"} and is_shield:
            self.last_shield_cast = (event.ability_name, event.timestamp)
            return event
        if event.type == "shield" and is_unknown_ability(event.ability_name):
            name = None
            if self.last_shield_cast and abs(event.timestamp - self.last_shield_cast[1]) <= 3:
                name = self.last_shield_cast[0]
            elif len(self.shield_abilities) == 1:
                name = next(iter(self.shield_abilities))
            return replace(event, ability_name=name) if name else event
        if event.type != "heal" or not is_unknown_ability(event.ability_name):
            return event
        name = None
        if self.last_healing_cast and abs(event.timestamp - self.last_healing_cast[1]) <= 3:
            name = self.last_healing_cast[0]
        elif len(self.healing_abilities) == 1:
            name = next(iter(self.healing_abilities))
        return replace(event, ability_name=name) if name else event


class CombatSession:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.total_damage = 0.0
        self.total_healing = 0.0
        self.total_shielding = 0.0
        self.highest_critical_hit = 0.0
        self.highest_heavy_hit = 0.0
        self.highest_devastating_hit = 0.0
        self.damage_hit_count = 0
        self.critical_hit_count = 0
        self.heavy_hit_count = 0
        self.devastating_hit_count = 0
        self.started_at: float | None = None
        self.last_event_at: float | None = None
        self.encounter_started_at: float | None = None
        self.completed_combat_time = 0.0
        self.is_active = False
        self.in_run = False
        self.run_controlled = False
        self.has_encounter_timing = False
        self.abilities: dict[str, list[Any]] = {}
        self.seen_event_ids: set[str] = set()
        self.seen_sequences: set[float] = set()
        self.recent_damage: deque[tuple[float, float]] = deque()
        self.recent_healing: deque[tuple[float, float]] = deque()

    def _close_encounter(self, at: float) -> None:
        if self.encounter_started_at is not None:
            self.completed_combat_time += max(0.0, at - self.encounter_started_at)
            self.encounter_started_at = None

    @staticmethod
    def _add_recent(queue: deque[tuple[float, float]], at: float, amount: float) -> None:
        queue.append((at, amount))
        while queue and at - queue[0][0] > 30:
            queue.popleft()

    def apply(self, event: CombatEvent) -> None:
        if ((event.event_id and event.event_id in self.seen_event_ids)
                or (event.sequence is not None and event.sequence in self.seen_sequences)):
            return
        self._remember(event)
        if event.type == "combat_start":
            # Selecting a new log is the only automatic run reset. A repeated
            # RUN_START inside the active file must never clear visible totals.
            if self.started_at is None:
                self.started_at = self.last_event_at = event.timestamp
                self.is_active = True
                self.in_run = True
                self.run_controlled = True
            return

        if event.type == "encounter_start":
            self.has_encounter_timing = True
            if self.encounter_started_at is not None:
                self._close_encounter(event.timestamp)
            self.encounter_started_at = self.last_event_at = event.timestamp
            self.is_active = True
            self.in_run = True
            return
        if event.type == "encounter_end":
            self.has_encounter_timing = True
            self._close_encounter(event.timestamp)
            self.last_event_at = event.timestamp
            self.is_active = False
            return
        if event.type == "combat_end":
            self._close_encounter(event.timestamp)
            self.last_event_at = event.timestamp
            self.is_active = False
            self.in_run = False
            self.run_controlled = False
            return
        if event.type not in {"damage", "heal", "shield"} or event.amount <= 0 or not is_own_event(event):
            return
        if not self.is_active:
            self.started_at = self.started_at or event.timestamp
            self.is_active = True
        self.in_run = True
        self.last_event_at = event.timestamp
        if event.type == "damage":
            self.total_damage += event.amount
            self._add_recent(self.recent_damage, event.timestamp, event.amount)
            self.damage_hit_count += 1
            self.critical_hit_count += int(event.critical)
            self.heavy_hit_count += int(event.heavy_hit)
            self.devastating_hit_count += int(event.critical and event.heavy_hit)
            if event.critical and event.heavy_hit:
                self.highest_devastating_hit = max(self.highest_devastating_hit, event.amount)
            elif event.critical:
                self.highest_critical_hit = max(self.highest_critical_hit, event.amount)
            elif event.heavy_hit:
                self.highest_heavy_hit = max(self.highest_heavy_hit, event.amount)
        elif event.type == "heal":
            self.total_healing += event.amount
            self._add_recent(self.recent_healing, event.timestamp, event.amount)
        else:
            self.total_shielding += event.amount
        key = (event.ability_id or event.ability_name).lower()
        if key not in self.abilities:
            self.abilities[key] = [
                event.ability_name, 0.0, set(),
                {"normal": [0, 0.0], "crit": [0, 0.0], "heavy": [0, 0.0], "dev": [0, 0.0]},
                0.0,
            ]
        ability = self.abilities[key]
        ability[1] += event.amount
        if event.type == "damage":
            category = "dev" if event.critical and event.heavy_hit else "crit" if event.critical else "heavy" if event.heavy_hit else "normal"
            ability[3][category][0] += 1
            ability[3][category][1] += event.amount
            if event.impact_type:
                ability[2].add(event.impact_type)
        else:
            ability[4] += event.amount

    def _remember(self, event: CombatEvent) -> None:
        if event.event_id:
            self.seen_event_ids.add(event.event_id)
        if event.sequence is not None:
            self.seen_sequences.add(event.sequence)

    @staticmethod
    def _rolling(queue: deque[tuple[float, float]], now: float) -> float:
        while queue and now - queue[0][0] > 30:
            queue.popleft()
        return sum(amount for _, amount in queue) / 30.0

    def snapshot(self) -> dict[str, Any]:
        now = utc_now()
        if self.is_active and not self.run_controlled and self.last_event_at is not None and now - self.last_event_at > 12:
            self.is_active = False
        if self.has_encounter_timing:
            duration = self.completed_combat_time + (max(0.0, now - self.encounter_started_at) if self.encounter_started_at is not None else 0.0)
        elif self.started_at is None:
            duration = 0.0
        else:
            end = now if self.is_active else (self.last_event_at or self.started_at)
            duration = max(0.0, end - self.started_at)
        visible = sorted((row for row in self.abilities.values() if not is_unknown_ability(row[0])), key=lambda row: row[1], reverse=True)
        largest = visible[0][1] if visible else 1.0
        top = []
        for name, amount, impact_types, buckets, non_damage in visible[:6]:
            damage_amount = sum(float(bucket[1]) for bucket in buckets.values())
            breakdown = {}
            for category, bucket in buckets.items():
                category_hits = int(bucket[0])
                category_damage = float(bucket[1])
                breakdown[category] = {
                    "hits": category_hits,
                    "damage": category_damage,
                    "percent": category_damage * 100.0 / damage_amount if damage_amount else 0.0,
                    "average": category_damage / category_hits if category_hits else 0.0,
                }
            top.append({
                "name": name,
                "amount": amount,
                "percent": amount / largest * 100.0,
                "damage_type": " / ".join(sorted(impact_types, key=str.casefold)).upper(),
                "breakdown": breakdown,
                "non_damage": float(non_damage),
                "segments": {
                    "normal": (float(buckets["normal"][1]) + float(non_damage)) * 100.0 / largest,
                    "crit": float(buckets["crit"][1]) * 100.0 / largest,
                    "heavy": float(buckets["heavy"][1]) * 100.0 / largest,
                    "dev": float(buckets["dev"][1]) * 100.0 / largest,
                },
            })
        hits = self.damage_hit_count or 1
        return {
            "damage": self.total_damage, "healing": self.total_healing, "shielding": self.total_shielding,
            "dps": self._rolling(self.recent_damage, now), "hps": self._rolling(self.recent_healing, now),
            "duration": duration, "active": self.is_active, "in_run": self.in_run, "abilities": top,
            "highest_crit": self.highest_critical_hit, "highest_heavy": self.highest_heavy_hit,
            "highest_dev": self.highest_devastating_hit,
            "crit_rate": self.critical_hit_count * 100.0 / hits if self.damage_hit_count else 0.0,
            "heavy_rate": self.heavy_hit_count * 100.0 / hits if self.damage_hit_count else 0.0,
            "dev_rate": self.devastating_hit_count * 100.0 / hits if self.damage_hit_count else 0.0,
        }


ICON_DATA: dict[str, str] = {
    "blackholebomb": "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAAAXNSR0IArs4c6QAAAxhJREFUaIHtWk1IVFEUfjM9HRmkxsK0cAJLAxM0WoxTiVpIiLoMdJEatDehoKJc1S4X/SxaRBCTCwfctGgQEXKmghkjUhcWKQYqWkk5SAnp0LTJ734v7sMnGXrAb/W9w3nv3sP5OPecO+NqKe9KG39w4Gixa5X78nevUmO0LwH+ZOSysRFoKe8Cz0qVgrvTu8Azf/m1795/r+zuDdnNJkJ8AK7rbU/xUHW+HnLq7rgLe3VzENJaSMLFIi2Gv6BwTf761Tj45FwMH/X9bLLdq84oPgPiAzC52rBsQsOXwPsHU0hxlHxqm04hrQPh5/CZnvkInxPB09qFf2TOqopHsllKT8DudRWl6RXm8BGfAfEBmFxJuNqwbM7UmPBZOXsBPON4NnxC145pF+gfTGntbx9GSBIRsH2eWmV2G1o5LbunyUU4xAdgORxuX3kBPtqXQMqaWDaV2eAsrfaSmXUtHDVbwct3NIDPLnwAP+LtBE96wuBZqdLtKrRlYPIDVyQ+pLja2MlmbOkm+ELuV+1iOfN7wKu9IfCooeSUaxSDew6/wR4OLlfBPjkXAxefAfEBWKoQT0kG9R7cFzmRzd68Iu1iXz5PgLOcuNo0PsgHX3n5XbvXxs4cGMVnQHwA5tou9pjfqaaq/XkB8NmpIQfvflMP+nbJAm7RGeIzID6Af5KQ6VHTnBPZOAEflK0dj8D5QoAhPgPiA3AkIbupig8jS1VxgNxF1fMY3rX9t6vQVoWthAL1NdwnoS+6964AxvYS1cOMLaq+iA84BsuG+x/+Jsv1r3sn7TfFZ0B8ABYJldVVgA9FBiGbQu8h2PsNNdTbycm2t6FqYycbbqEHetV1ZVldhZL0iPqO+AyID8DFU1h1cxDcH6zQDvLPbiXB+Y6Iwf52sJNNww2f1mc6noCEoj1x2MVnQHwAJleeaE9cDfJXT8LOqQz3qhY3sKQOO65a3Q4WthxSVG0yKi/Cx9pax7UVSXwGxAfwX35mXS9Yxjk+dV6xpM/dUdKKPY5sS2jLwLVZf/awAx+sLK3kJzXxTQ2PY8/iMyA+gN8HEw/q5vxLzwAAAABJRU5ErkJggg==",
    "bomb": "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAAAXNSR0IArs4c6QAAA1JJREFUaIHtWk1IVFEUfm98g+k04kxZRjml/dBAjUgKThIT9EPmRsyhHCVEUWjXUvrbJLlt1SIpJGQoFFuZLsJw4Q9ZBCYZCVpmRmZj4egUk/PafedM3Ne8oc1cmG/13TfnnvcO5+Occ98bVTFAk6cc3BbTwNcsv3WRvS2mqcwG1+9PjhvdAtAvxi8Zh0/1gXivJaH3FIf0Aah8YUY2RVG70NGsdRXc9X0DfudzM3Cdy0l/4qXNUx8TPuhGtVd4XfoMSB+A2rZnHxb7M7LBR2zZQtmEI3Pgp9/bhE67PVng28MkpwIvyel4VQ64O3cV94rlO2FveT5DTl1bYBOtJKlLnwHpA9C4bGY21pGmzhAVqOGFCPiouxDct2tJ7HWS7Ls9WfD55TWZXKqnqsUlYR0Yh/3bRWqOB0fHaHNaQikEtclTzmQT+ZetoiiK4is9Af75xUPwHaUXhPbzE2PC6wHrV/COO3ngzW00CjUd+wEJeUtYz41EQaXPgPQBaEY/DC8Qv1FNsrl98xqzIn6+8pDQT13rFfCRV7PgQSatYAvZB6zL4BVVedDTRP8yNFS2OoPr0mdA+gDUIaVYeMIykk3NmSpwh5OaYHhlGjyq7wbvG+wH7+kLCh+CS4tXrZM0/igNfhr9fR7aK30GpA8grpG9KzqKH5KVDcdmhxt8JbQObkZOg72PhXs/dJJNepxOJcQ1Mj7b8CZlJBsulSPqGvhwiGwcTrIxA/veYvCVEFWkv0ZucOkzIH0A2nK+Cw2i9lwDKpLRbMPBZcNH8QNJPgRvZEbIKBgCf8bmNOkzIH0AWkzJxIKn8tHAFHhzwA/Oq9BLnd4LtTiZ15AitOfNq7fzFrjRaY7DcpcqoXKWGpz0GZA+gLhZ6Ok3OjjXtdaD+2sC4EZyMkJti/hExsEbKG+O3L9fIwkdLrTT68eET5DikD4Aw0M9B68e94I9Ce0vX28HN1NtzMhmKWcr+PhiugqlDgxfLRbqlD5XGX2fqigpSuoGvPKYqTb8hcCcSlK5qtHcxeUkfQakD0Dz/VTRFDrs2yCnrmn6eNGoiN8wJ4tkZWMG0mdA+gDUdvcpLDaFw+BvHDrk1MC+eTXuZGPtf6DrE0mFf5Y180+AzOiv9CyUMvgD0cIoulp19QEAAAAASUVORK5CYII=",
    "chainlightning": "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAAAXNSR0IArs4c6QAAAydJREFUaIHtWUFLVFEUfvfNa2YUR0EmA7URkmBAkYqioLEgWlarFkVto3LTpo3+gCRw40aCoJ37QNxEK3OhNLuMhLJyLK1pNqMwOuPMve3Od95wL8+JFh7wrL535p577uH75tx371PGGC/KlFKRY1xWXRjCQzoDXCoY5lfMb53HlKtYT1eCYv1/XtkhMfEFqCYJ8QeitfZu+H/lA/W5e+TUi7OhNdHgYgXOnnaK1Ssl8otnQHwBQdMz0ddYnyGnqwO4zJSrNI/qSuAH1m304mx0F0rECHLZeJ1xGi+eAfEFBHyT4puOSzacSjXQiY6xvo0OM5wmrLI5JKiUMT+TK5eNKy+XpbddIyieAfEFqJZl09OuGLZ2JL5JhZJ5rNt47chbWCKsC/OReZO3vyGXNZMgE19AaCNzyqa3A7LpTlrHcNMr04STj38RrptJq+SCgeeEa4V55D2ZQpfb2LHmEs+A+AJCXchjr7tmpwbZpOLwFyugda+OSL65DN4kHBu6Btx31yqhupnEQwndRq++JHfiykdrAeIZEF9A4IVPYWRcNk0bCuG2+xuE9/UzawLl9RPW5hPk4b3G+5KXhSzTqzTeJRtu4hkQX4CqLgxFHrTNfhIUbxURzTpP8OgJn9d6OeAy38sBq1H7Qh13U+IZEF+Aqn2/Y/8hM4IuxOTEO1JwdRy8HkesqeD1WGVGCB/zJ6y5XHdT9fdTNH89P2WNFc+A+AJCf22+GZnSOgalB4jWQI1bJ+LXj7HMGLpW5Qv5G2tzCKg2+HjCwYWnmPPNA8J6bc7a2cQzIL4A5yYTercp43pQf3hFVMZHVyITuG62m05ztI62sd/k3J05wcccSehQ2oE+ftWKDxHg6EhcKlwescs37Dk6ujGnTsM/iO5UfzHNI44kdCit+QMHWWhT2/xhHcNlo4IzoPXsFmKrfwj75y9Z5ccP9Tq/1NI3XfEMiC8gJCF+R6SX3xL2L17HKy7rDP45yMak9sivurLAvf3WWO+WD6nssm9h+eUWT3PCTXwBIYpc14zhm+o+yGbzJ7pK+FBPxmWjTp1G7NfPB1lfpJzEMyC+gL+GUTIOjGEWdAAAAABJRU5ErkJggg==",
    "chakram": "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAAAXNSR0IArs4c6QAAA49JREFUaIHtWU1IVFEUfs95M/PmF81Sc/KHfmRSI5IMggqsNjKL3Fm0KAINAyGQlBZhLlxELQTDKA1sIeJORJEgClKIZgILKlTE8qcySzJnUsenTbvvnJH7UGvjDc/qu2fO3HfPnG++d+696qnMcoVZjGFV+XuLiZyprgLM6UrIgl9fyQduHMzY0IMSNry0TWbSJ6Ap5rSB36MnC+kUXpxBjE1zIEZLsAEnulLZ/BFgPUq0Uf6BrtJXQPoENLMPOCU8jmSUPrwwA3+Sayeww+ZBzOcfw5jHa89CjF3dAf+8FqJF/E4DrvRPAK9HkaSvgPQJaLrVjRIvGqQSXEk4JdKTcoSqFTXmVVFMYvQM8Ky9Q7gI53Ih8LI6jXk4nbhxaklfAekTUEtyrmPA1YbTZpvuR1lVLQK/3epE/Bd1DjHZvgOIiU6OMTqVChfBqWUWo5i87KSvgPQJaB5HMgYrS6RIuc4bXD2AIzHqi1z7dKJNyi7M0xl8jPi2hntrLiI0cha4cG8qcHfFFA8Tqp/0FZA+gbh/9qV8UgPDMiFUD64YvdZB4LbbYqqcv1YB/LDgDnBLrB84u+8gcPVTouL7oWXgVXSCSV8B6ROIa6cNi7j34MZpwy008hW44f5NYDPavBjoJOwmrJysBeR0unv8DXDx6GFg6SsgfQIaPxeKGvPAdqsTuN1dJ/zy1ctEFU4bboGiVuCPfV7a7Bt+qNyg+gv+dncd/NVK85oJSF8B6RPQPDr1QjORSZQvPSkH/m8hKmV9yydgTpt0bxrt4OamhEeLx9JI9MKZKr1Ex12I/7Ch5f8HFZA+AU2z2DDgtDHbGXHaFBt+4LezrFdhP0vPs4vAgaJWUOXVz1xQaGj8HWIGuoiuvBfi/ZLiEz5KTpM+Ac1rycXAUNbuhY4eKqFBkPqiDBsdD+Y56RCgJdZPisTo1M38Tb1V8D/qIZVr7qAWvcZXCezbowNLXwHpE1DL8nox0FfyxXdbVfTOuRAgCbhS2wOcGBS32dxmj5BqNdUFgLnalNeTytXExLR58jwMLH0FpE9A41eciskdGVcDRaFNOqeBohDm1OLW9YBieE8VpzbroE3Kdm3rXGjTWNy50KoLBVBov88K5y21EbislOj0MvgamG/YzexchDbvp094hDFmtJn+TqolfQWkT8CUQh66ZVXCCzEhndZjXEnMjFNld5ZNeJExOrYEvHVHtpnsDwjTF87lraiZAAAAAElFTkSuQmCC",
    "drone": "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAAAXNSR0IArs4c6QAAA4dJREFUaIHdml1IVEEUx8+Na2JaWvZBKWZld9GClEq7ECzhPtRDn5ZFRQ/CPkhRIfTgg2kW9BILBlEgbBAUSEmaYEFruRCsEQtblOa62Sa7lEpSiooabA/VuefWnO72IO34f/rPeObuDPNjznyogHssBgKV62noO/WlohDY5DggrM9bsxF9c2M9+iFXmIYpSaEuAACYydsm7MNvUkSV8+JomNCSfgAKuMewUK6n4VRSbFblF6JflrVW+CGKDae/4cQ04dBSCoL9AACgatNvSf0Wy07MlpI/BgEAYGql9k/t5EeovCcmxKbMeR6979kD9BQhDpucnDxh/cBACL3n3m30fTUdpj5tyJ4PAABvItNYaff5hTipwl9KEK2HCcsY+RFanpGJU0Ox4URxOny0ShhDUeHajn8yVr+i9uds/754vAAAMPXKVI99TmiEqJKy09HPRL6ilx4h0wxwqweVj/imOy7LeH37HsuYYIVDWK+5PbEMh/1XEXGCiJH4pEGIKlVfjV56hJTKcw3CBBF6/xr9cLQfPV15nnhbhB+lCY5+J+x/if7KjZuWnautO41ec3tM/e5+9CP5ST8D0g9ApVNMRbGZDdlsK4T1vb2D6C/UXUVfS1aqgLMlBuklADAHZkD6AZjyAIdNPMkonpWnoqrW8jsULYoTJ+lnQPoBmLbT9PBORZMXt1XmsGl72i6Mv99mbKH37y4RxjRcM05tOx3GKkQTnPQzIP0A1PxDzVjouVuGPp7TGT2YU3HYUFFs4sGJk/QzIP0AVCDXekOuMK5Inoullo05VLgExO1/OJziaau+m+ghxc3CoESW/AhFSo/TMuLUV9OBOBU27sMAusXlUNkbzUFPH0rq4bNlh2iiPHPyGHoOLdNmLiUcQD+ZK87KiSb5EbL7/Fjo1oyb50mmQXfQeJgo0HLRs9ikWGPD7Xk4bALf8tFLPwPSD0AFctNbEOxXxlIXAADAcOZiXJE0twdjmsjhmm6zW+nL0IBhj5CtL30cOeU8K+wQRZSq+tZD9FlLFinRkVEcgFBbQy+Mgr6DC/svio6MQtE6GwDMEYSoYgvHfz7rjBtjG3R50QecxnVi4Ho1+ssndqGnt9YcNhQVepqjN+QcNvbCg/I9cERHRqHYVvxHvfQIKXZnJ/c3y3/A8Opk90pwomq9VImeYkNvth9/SBa25bChSmiE6GrDSXqEvgPayzIHNTLMcgAAAABJRU5ErkJggg==",
    "fortify": "iVBORw0KGgoAAAANSUhEUgAAACoAAAAwCAYAAABnjuimAAAAAXNSR0IArs4c6QAAAsZJREFUWIXtWUFrE0EUni2zSWyaxqayhoKC2Ip4qQURA3pRCrYHD1ooPYjgRf+BFEQQxOJJ6EF66iVXc1VB9BoPBe2lSFsQLJS4YLSNIU23aE/95luZwe0h4IN8p29mZ2Yf73v73syspwjXJx+AZwoB+G7U/nPAT12bQH9zdd3wre+esiCbH8Tc7Jlh9H959xo85acxd6ceov/Nq2fgPbbF/0eIMVRPTj9Fw9c++E49hGTFcxfQP1w6D77M0m/XMZ6RzQ9a53LY1FaWMDc9cAxhwLaJ8agYQ7VSCm6P9iI8YLn5a3VhZGYMvPZx0zxo2sfzmkXqDzfWrCEkxqNiDNW/G1touOS+feskTamDLR/yZaUhM7dEa5YrZkxA42srS+BiPCrGUO16wMmZ5V6Yew+ev9wHPnPlInj1dAH8w8tF69z7s1et7+IiwhDjUTGGejem59DYbfxEsu3J5dEfnBgBd8nNqG4WrP1vn5h38Zrhxho4Z6FUbw51X4xHxRjqTdx8bBq+D+lzZ4+jvzg2BO6S24UkYcBg6ZVSXek7Bp3q60cjarfAG5+/WSdwMmdwHWe516ufrOM5tFzvSuWOgovxqBhDddRu4UvnJOza5j2fN7X70tRd8CRy81n+0Yt74OXKV3A+9PFuX4xHxRjq3OaxBLwDZ7k5aY8/nLWuw3LzmHLFhEfTsbVjiPGoGEM136Tx1Qof9FgaFonrcpLazdnAJTcf6DKFoFvrOwbNF6eZ/gFrGMR2+46FktTuv5I5OIcH28C2ifGoGENj9+58h6/oUlftRdYw4ASeZJvHyT+2k9e+sYNuFLt3+J2E9ZeLUvEw8DK9htMBkLeFo3emwF2JnZN5ErkZYjwqxlCn9Az+jZI+Yq502q1f//yjF6vdnMy3f6DfJTdDjEfFGJpIegaHQTYwP16aYQ1h4Kzdh5SbIcajYgzdB2byDhdJZKoUAAAAAElFTkSuQmCC",
    "gleamtwins": "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAAAXNSR0IArs4c6QAAAu1JREFUaIHtmU9oE0EUxmfK4kGqDQjZRCOIJB56EXMTitEitBaP4klFsQqCVBD1Uqi04MEiKip48KBUPAhFBC9Vof4riIdGTwvNVglIMAlEgqbSWnQ95b1vYcZs7KUP/E6/mbyZ3cf7Mm830er6TWVSZ7lO3EjEgiZnbkwY423yb53gPfOfNO2Z3cpBAyfb2hPV8c8rV4nEJ6Bjx87QoL49HZiCshOviX+eum3caPO7PHFQekn8ce45MdpJJdZr5i6er/9g/txgri4w134Riq+A+AScul4k26BVUDbbpB5dJTZ6729KdJmXxNYyF2vMYJtOv0j2E18B8Qk42Q9faXCl+z7xUK5hig/Z5sKGEeKSt0T8wL3c8sKZnpGWMTb5Q0fIfuIrID4BPX2ITyGbbbBJnV/cRYy28bxl4vd72GbYyNbFthC32xCrFZ/4e71ILL4C4hNwznmHaZCqZYixZCrLzzDjtTHiHd5Z46ahtaCVNES0DVpRfAXEJ6D3DT4zVs12AsRdttlUX9K4afnbaeK9yZoxBm1zb+clY8zRt8PEeJqhxFdAfAIODir5O8QunDwKLIR26n/KIWgDm22wSd212MYrLBnn070cj/cpvgLiE3DwtEHZ5lFop4HHB4lTbuuGiCeM7bG8qnitu2m38R7EV0B8AqFTCJ83sGHZhPF4SqDiwHh64P694y+Ma7P7meen2XL/n4VWkxzbBxq/9Za3IZuiNERU//E3xLY3L7QNSnwFxCfg4GOq7STBUuYKk8Svth0gbrch2t7abBa1zYuvgPgEHH+GX9JVz7AxCG0TRStpiP61h21dS3wFxCfgqECNNgf+zNhFU5Bf8UZN8xmljPGoKA0xZGM1xwj3pnTHE+L5xGwTxVdAfAJOqDTBb3MUxoByhUmyEDa1KA0xZBubVVQwywg/X6XLhOIrID4BrUpTMLT9Nsx/qifX8N+gX5YXaMFgvJvm0U6oSLYJwDaar6s29hn3FF8B8Qn8Ab+WKDfzp2QoAAAAAElFTkSuQmCC",
    "healingpulse": "iVBORw0KGgoAAAANSUhEUgAAACcAAAAqCAYAAAAwPULrAAAAAXNSR0IArs4c6QAAAvJJREFUWIXtWF1Ik2EU/pbf3MSftbnswlk523QiWmogVktJuuwi70IzAosoKcqLiK4iKiKLLiwQCsorIQn6I8GNIFnfhX+LkbKBhn5hmW21rKkN19We90xeWWXQe7Fz9XzP97znHM7Zefe+n8Z07bQUt5/z/lgca7PsGsJD8+3icymZ3Qocp48xguGzQ2lM6mddUsV/NKGTk2krjbYzeBEK3OC24y8Maz2qA6TdpAL7g5YY4aEXunJCJ6f5nWnNnzFA01R8ANhszOA6nQtFgAeGpoG9Tj2VIdbZml6QdIqFrpzQycl0g5XIZFG+qfgK8MDQNNpx7mgt1+nVLg/wrqoC+PRKn8DTqexQGlPT+k9Ns+J/EHbKdgf4bg9rcYnVjBbUVhu5az2DIeDxiTm0ab7yJtOQDZnaa7UUWOjKCZ2cLJHN0P10Gi3IbtgGkXv4EXCJtfWPAtC1Y+MLwC0HxxDXozoQd6q5ARqhKyd0cpq2PnZM+jDFpuxFz0iMtyAvzMr+oPM81+mhE5eBZ3P6uRpjy3XgHfITtNVZvQRe6MoJnZy81RpB+/r6i/Aiz6xFqUuz90Ozt6YMmtU24bZjJ4FdSh3w6MJj+Azdb4fPyd3boXFW68ELXTmhk5PpQ5WTHZm8D01EFQTvUnzcKabmUnzctdrwD9DazeXgA6/YztC7oT51ZFqzaTZ196OkjjQvu2Pe66Y6aOoKL4EstORx77OT6iz0LycvJMSLg8w9zSDTt1RAv/TOm2rrmk3Wv1HwELHpgMsqc4F9w5+BB9/fRtlHZ5ieWnR5kbabO9369Rbg5VV4oSsndHIJm7ApLQhc32rnnpDdz9Skm/AKw1p9xT6ugP60ohtTbV27yRIp+9vxTLSs3vkFou86dpe07rRAn6ULgzdnMJxtSAeOZBQAf81hfvzBXMSKLkbgU/7IPioKXTmhk0uY1iIrK29nVz6dSuCFcjZxR8hHP0kySHxjF5YOxUJfIBad0In2w8BCV07o5H4BT7/k67qiWgoAAAAASUVORK5CYII=",
    "icecube": "iVBORw0KGgoAAAANSUhEUgAAAC0AAAAtCAYAAAA6GuKaAAAAAXNSR0IArs4c6QAAAtBJREFUWIXtWd9Lk2EU/j6bI+fnUnOfW5kQS0crL7qIwKQtIvsFRkQQFCJsdtNtd4EXkv9Al9mgLoIuIsgbyauCkmGURWZroKHV1KkU0ialaFc95yzel2+DGBzwuXq+85733eGch/P+mGmUEz3XivHa1NjNv6TivwRTZogM2iyqZPfuEB8adPZ//EpprszlwdeqPY4y0EFkpkUG/a88qGS766hM3iryqGG8qR7+kVwI/r6Zdbg8Sj1UysA3kQKvC53D3O1VPtgXNr5yjnVEZlpk0C7dQK1lgf/Y76cSs84QWT+Ish7yNcHubbDg39dxS7l+0v2WfyoltJSfIom6yS4y0yKD1srj4o1ulCzROwD7sfAJlCziOUxlzdHc9iB1gHBIvX578CT46NQieHKMZJNxL2J93m1EZlpk0C5/azM+5tOz4InhEeWEaP1xlIzL4FSUfL7MqX9s8hNxLolikG/YuXU0LTtc8+lZlDs2eBMDXB58g4ifJUnsCagX5fanz4hzSXBpcSTHiPvHJ8B/+m1wkZkWGbR2c9FBJwneMXRdQicJjpHQR/DG31F0DGucdCYy0yKD1sqjL3senHcMjlIlodtQCmTz/gPowg4v2d+NgorMtMigzdjaDB1B2YYSO9MJftfVbKjANw4drk8vK+1XNjfA++0nNMDfTPjl+sg+UJGZFhl0YfdgpbGDcfB4Kx1ZL71QS4V3hgemcy4KOsZ9JomjLSSJxlp+4d06mpYdrkR20tHJTjtLgoN3Bi4Vbj/95jb4rsudKH2mrZokMb1MUvm+Cioy0yKDLvlo+pwuEEa2Y1Xpw+UUZZ2nn72fGAMXQDP8Wew1vZQaAXb26LoKKjLTIoM2jW/DdLG1wxjgT2Elo+2A2t7iUdsDXvX/LHMrxLt6QUVmWmTQ5t6ll/j4/GtFKRUdtBvTUIrKXVFJdmsb8RpN42Iy0EFkpkUG/QfUGse1mx6jwQAAAABJRU5ErkJggg==",
    "kusarigama": "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAAAXNSR0IArs4c6QAAA95JREFUaIHtmV1IU2EYx8+Zp53pdmY7rVN+NNNabW6pZYpYVqjUTfRhUdBF1EXfSBdFV9FNXRcRREFdVFeBghVFRVghhEhEn+ZHmGbqNDPn3Gqlrqv+zyu8Q4Uu9oLP1e999u55z7Pnf96vydWeboln3ow5XD9rGUssU/b5OTrO5f7BMXD0Tww8356ExreRcfkfF6y0cuObpnyCBDfhE1AkSYoxbTlOP/TRHAr69GkkibRQUkziWLItCTzU/wdsT6bf7uMQ+QdDE2CTEQZ3dCngnCwVYwlfAeETUCRGNk6N8glHqZRWlfx2XUH57CEKdK0oMvVoRXH8TW+47sUN+RirzxUkeXelgoWvgPAJyJcrAmh8Db0HZ2p+lO9jD80SnWVU7vJLef/nKdoXAesb+8jf9Aq4uCEfPOwKzEooYUxpHniHRq6xArKpbT8Df8qmLeBHN3YyTIE8mcvBThMtOtOxwQnaF+1vvgeul1aBOyWS04+XjWDhKyB8AnK1pxuyaY6cxQcNgZvcL/iytmIGMGI6/AtSMsFjE6PgmrYL3D1SPMlNktOd1+Bb+0i679/dBwtfAeETkCtcB1FiVjZex3pIJUtbCf8SrRzs1vO48piOsYsjax/GtoFZObV8bQXbU9NmF7KEsUkrTtH8KpTGr9Nbn2+UcqXCyqBLaeV1kYod2YjZM/wQ/usdJxDziM8L/2CQtvGsbLRkDXFGgrRfEr4Cwicgm80WlLIy8yjKtDn7FHc77dRM6PNjfAT+wC/iiImOanNNj8G9o3VgX6oV8Z/Gkc3qrAqMle2gmXBXwUmw8BUQPoFJh3rFZMYHLdEWeuv1Hvi/O4bAv2293KCx7jZwMER9piObpTklGFfX3fDv8p/k3l8JXwHhE5BXFe5Aw+OjLW5vzxewRc1A+Qb6P8G/bTed1F48a5Z4fcomOsDxZFNeeZz7cGwct14A2aSrLviFr4DwCchl6w6gEQ4PQSqsPM6dPjSjoKfPXQXXXDkPZmUzHWOlxcpJVW2zs1DCmLyh/BgaFosNEqp/chH+hekulExV6X8xh54G3rx9D75bd/su/OwBPEVNRpxI9Cf3gaxWuihgJR1PTsJXQPgEFPZ0Y7G4uZ2WeeifiVw/Xfc5DeeUsjEMN2STOo/k4fUXgkOhfvDTh7Xc0x8raXaWE74CwieghMPf0ah/8gDMvvWlG3K5ZY0nG/behpWNqpDkItFh+Nes3QhOMqvgtldvwXsPV4PZhVX4CgifgGw208JkGDQLDQy0z+jakJUNO7OVlFWBbQ66QCgpXg9/Y9NzcOBzEMzKkjWvv3B2L5Qw9hfQmEenCdPf3wAAAABJRU5ErkJggg==",
    "machinegun": "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAAAXNSR0IArs4c6QAAAzJJREFUaIHtmU1IVFEUx+97Ppv8TJqaslFBcjMSDKW0iIrQKAzKkKhs0we4jQiCFi5d1LKtwbRoJYRoUG1UMEnEUhMrJWSmSBlnRoeasRm/3rx2/3uU+3hORnjAs/rf++69j8P5ce6592pWv6BmiWzsmbrb7PU7Th0sWlH2v0qt0qbmtI7u+KdtbuwdMIQdNhQPS9Rms6juD45gaiIf/YtrBnT5Si70cMIFXZojqQmblh3SGMQ+Auwd0Kx20nonav7Xj9s/eoFZ8FfeX6/DPgLsHTDEIMlCd8gXm02Kmt2GtclNys4cN6/H36ah2UeAvQOa1S8R8jS6s5pcXOhS9l8x8pX9L9ZSWY3fYEq02EeAvQOG3Ydyn8ww12/cc1yor78bOtDTBU0xa2h+oJwbeNoG3XlwP+qu3qUVbHZpodO6aKcW2jamWbfIRnZbfqAZqebsZejobEi50KYwez0EPdN0H/rM1+fQHTY4PfqZAE5RM4Mx7CPA3gHNuklKaE18UA3ydEmcgq3V0HOfE9AdQx7lDzpLTOhkJAl99eUw9JuWeugTJy/KNQlOdsY+Auwd0DKXCtDIjFUhI+XUj6OfIrQVu9bSCj0d+gRtl9n8v2Xt1FCiLsXZR4C9A5p5+gAaemUEGcns8yMjlSZnMCbbLPQkPApN6ytqPybHlf3H9lZCHypUl23sI8DeAUOvi6Bhzeah3sipG0cdEqY4tX2xWWrGpl+axyuRqKo8At1BEKL1T9NciGyscu5oXGYt9hFg78C6Qz29C7IMF0492uoyspOn242wbqUuojhRGyGnufU4xfDfkl0FOyeybWO2JzKK02gkHyHLuOQdTu2eeSVa/8qijQtAKDDhRoZ8GJRj2EeAvQNa9G4RGlM9ZcDp1PFJ5YSBYR90uigOtBZyZenbfDgJtAbe+7JCS8tYwGZCX5Qba64knT6IsI8AeweMqZ4yNCq8MSARi0u0Uul1t9CI5TlfBJqiNbaUxjqmawk6JfcxceFoSImZpWvQ31O7HR1gHwH2Dji+RwkhxNtqiUeFNwa9AS3YfLxY+cJu90Z2ft+yRJe87IfJFWLYVD/as48Aewf+ALU0C2C6KmUhAAAAAElFTkSuQmCC",
    "minigun": "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAAAXNSR0IArs4c6QAAAtpJREFUaIHtmk1IVFEUx+/r3QpqbDFjYxj4lSNMimbZh9Amah0ErYo2EkREHwgtXJRai3aRRZsWbqRWLaqFEGQgRCkYlFSCM6UJDY6JLcbIKbN25/yDe5j3aPMOzFn933333evh/+Pec+/omeF7xhm+Zd2e/OPskyt4pH/84vZvK+7+HdXuuaSYyLGeLrKefEdyXbgRoxfqE7BmapGf0pVs/e9Vbn8ww3pfnLHZBPkjNoBKav8158SZ8asl+0j9MdQ7oD4Bz3SdYetbW/hNwmdUNrA0P2GBSdiS2GzeVuGc+Pt8wdkepH/m7mnS6h1Qn4A1VUnmI78Ar5IsY5Bn9XrGBjaX1DnG5sjxk6SfPbwf6g9CVCScEFf1DqhPwJob1/np1h13r+U1NzYDQ6RFuyHCrkhSO4Z6B9Qn4InYGEPYNGRytFL5wyPUjkhs3d5Aevb1W9Jd3b2kB2/2OyfCcSRsyrVQVMPGx9jupQNthEd6fIqwWR2boHZE4vnoI9KIDW5k/xOIFtZXiJN6B9Qn4LUc49K0+GbSeRgPi01NTSPpublsyXaslyT8sE+5nI5SWMQmSBkcFpvsDN/hYOD4dXvaSL968YS0dArDUO+A+gSshI1U+obFprGeLwokbL5++URaxAavJT8u0Sar3gH1CVjEQCprdzbVOT8Oiw2OL2Jz8RRPgNgUinz5sCNOUr0D6hOw+CDdyfT2XSDd33e75KBBVrPOg0ed/U3TRtYv84DNFm6v4NOiegfUJ/APQmg3WowRBCcsvzGkEhpXntholrBZ3l3PH4/Mc6l/gtvVO6A+Ae/x0/dkzYfpWXqBJy+MIJsUhnjPg9hkPjM2qVrulPBBw48pvi3XQpEJb1fnYbIGVxXESVo9wm5SgbDBH1mq4D8EcIMzpoxQZMI7e3mAbMIDtYSTFOImdaiddKy4xtjsbeWPL51n3XOFdX6BEWqu5booXUlSvQPqE/gLeogp8ai51SkAAAAASUVORK5CYII=",
    "pyrosphere": "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAAAAXNSR0IArs4c6QAAA3lJREFUaIHtWU1IVFEUvu9nRqdxZpSU0sY0wkqmMMFMBCEiIpBo6UJa5CIwwpa1KFq0a5UQuas2LWIoEBEmaCFEEOoqMy0htDIzZ7KZQWecnzet+s4ZuI+ZafUu+K2+e+bc896Z83Huee9p94KXxT9UuZfBv7t+Ff7xhq1uUQqhqgWpvXd/Vcm9S+uN4GFjTuoTLAQ03JsWh10vGd3hUD4B068nsEhkWiGbM1oK9mzwJ8rXFA3AZyrtgQ+Xyt6TX8FzoQy4frxeehM9ff20aJPfaNiYw3W5nJSvgPIJmAnLj9LwTqJ7AlLZdD8mH7veZAk/XeA5SVTMM/5wmPzfPAPvWRqU2sXQCVAuJ+UroHwC2svDXShHqroWsvkSb4T91qUpbOBdxRy+UdHFuCSsD1FpHO6j98nlND3UTj4V3YEDoXwCWrjzLBaLGweksrEGqKvw0nPYHVJcBnYoRzZFca6Pkb1kdIdD+QTMSmVTTufJjY2ylY0MykA5/spXQPkETLsfbGXDOoAtQvI4XE4clUqraO9/73QIlE/AVkJ2spmI7CsZtH+AnubKkQfvWpXOV8pXQPkEiiRU9ADO5pBJG9nM+urAO+qSGMUnr3hwOF68IO9a5Tzs281C716dJrt0p0JQPgHbLmQHLpvW3BZkE40ZsK/6fLQhQrT/CetOLKbtCM1eCFjsEAwbOWkcJaF8AmXNQkI0g3UlN8GjHjf4wT3b6DyJlAZpvfCbsM+ONMH/ztX37Fp8/CbcHz8PvvF6GrytvXr31aJjYC42LNFi3i11ajySQsnWPtMhtWx6wbPbJJukTj4tYEKMeLfBb47Wlry5o8EFxBSb9BFkbdm1+2rRMdAenOvAYiZGpX/auwr73bfHwFvSdHg1ZDPw/+SpgX3DpMqvaykmJzrgjEICTvEcHUxeQQei5qK34rz7/XDvdiHnwJyJ0Xeu4VNRlCYXInl0Rah8i9XknzC88PflSQZJk6TYnHfBZ8VIkpwEfViJuZPYW8NkxmXz26Q4TZk07MpXQPkENL5IPaInr4kIPSWNf/NJOwmHZaURq3uLOg8fv+t3qINlhQV7XneBZzWyWxr9v678DvjtjzQXKV8B5RMoGqc919bBBzsPgQcKbpT+j6BSxjXqVMIQNJ8w2fBOIoQoCCmog3HJrWjUnYSpF8kd15IHVAfKJ/AXPXYsyqmnxLkAAAAASUVORK5CYII=",
}


def default_record_data() -> dict[str, Any]:
    return {
        "HighestDamage": None, "HighestHealing": None,
        "HighestNormalHit": None, "HighestCriticalHit": None,
        "HighestHeavyHit": None, "HighestDevastatingHit": None,
        "BestDamage60": 0.0, "BestDamage60At": None,
        "BestHealing60": 0.0, "BestHealing60At": None,
        "BestRunDamage": 0.0, "BestRunDamageAt": None,
        "BestRunHealing": 0.0, "BestRunHealingAt": None,
        "LifetimeDamage": 0.0, "LifetimeHealing": 0.0, "RunsTracked": 0,
        "LastUpdatedUtc": None, "CountedLogs": [], "LogSequenceCheckpoints": {},
        "LogDamageTotals": {}, "LogHealingTotals": {}, "LogHitDamageTotals": {},
        "LifetimeHitDamage": {"Normal": 0.0, "Critical": 0.0, "Heavy": 0.0, "Devastating": 0.0},
        "RecentEventIds": [],
    }


def merge_defaults(loaded: Any, defaults: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(loaded, dict):
        return defaults
    result = dict(defaults)
    result.update(loaded)
    for key in ("LogSequenceCheckpoints", "LogDamageTotals", "LogHealingTotals", "LogHitDamageTotals"):
        if not isinstance(result.get(key), dict):
            result[key] = {}
    for key in ("CountedLogs", "RecentEventIds"):
        if not isinstance(result.get(key), list):
            result[key] = list(result.get(key) or [])
    if "LifetimeHitDamage" in defaults:
        hit_defaults = defaults["LifetimeHitDamage"]
        result["LifetimeHitDamage"] = merge_defaults(result.get("LifetimeHitDamage"), hit_defaults)
    return result


def dict_key_casefold(mapping: dict[str, Any], key: str) -> str | None:
    folded = key.casefold()
    return next((existing for existing in mapping if existing.casefold() == folded), None)


class FlexRecordStore:
    def __init__(self, records_path: Path | None = None) -> None:
        self.path = records_path or RECORDS_PATH
        self.active_log: str | None = None
        self.damage_window: deque[tuple[float, float]] = deque()
        self.healing_window: deque[tuple[float, float]] = deque()
        self.sequences_this_read: set[float] = set()
        self.ids_this_read: set[str] = set()
        self.dirty = False
        self.last_save = 0.0
        if records_path is None:
            self._migrate_legacy()
        self.data = self._load()
        self.save(force=True)

    def _migrate_legacy(self) -> None:
        if self.path.exists():
            return
        legacy = LOCAL_APP_DATA / "SoulboundMeter" / "records.txt"
        if legacy.resolve() == self.path.resolve() or not legacy.exists():
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(legacy, self.path)
        except OSError:
            pass

    def _load(self) -> dict[str, Any]:
        defaults = default_record_data()
        if not self.path.exists():
            return defaults
        try:
            return merge_defaults(json.loads(self.path.read_text(encoding="utf-8")), defaults)
        except (OSError, json.JSONDecodeError):
            try:
                recovery = self.path.with_name(f"{self.path.name}.recovery-{datetime.now():%Y%m%d%H%M%S}.txt")
                shutil.copyfile(self.path, recovery)
            except OSError:
                pass
            return defaults

    def begin_log(self, path: str) -> None:
        try:
            self.active_log = str(Path(path).resolve())
        except OSError:
            self.active_log = path
        self.damage_window.clear()
        self.healing_window.clear()
        self.sequences_this_read.clear()
        self.ids_this_read.clear()

    def _log_key(self) -> str:
        return self.active_log or "legacy-or-manual-source"

    def _persisted(self, event: CombatEvent) -> bool:
        log_key = self._log_key()
        checkpoints = self.data["LogSequenceCheckpoints"]
        actual_key = dict_key_casefold(checkpoints, log_key)
        if event.sequence is not None and actual_key is not None and event.sequence <= float(checkpoints[actual_key]):
            return True
        return bool(event.event_id and event.event_id in set(self.data["RecentEventIds"]))

    def _checkpoint(self, event: CombatEvent) -> None:
        if event.sequence is None:
            return
        log_key = self._log_key()
        checkpoints = self.data["LogSequenceCheckpoints"]
        actual_key = dict_key_casefold(checkpoints, log_key) or log_key
        if actual_key not in checkpoints or event.sequence > float(checkpoints[actual_key]):
            checkpoints[actual_key] = event.sequence
            self.dirty = True

    @staticmethod
    def _record(event: CombatEvent) -> dict[str, Any]:
        return {
            "Value": event.amount, "AbilityName": event.ability_name, "TargetName": event.target_name,
            "Timestamp": timestamp_text(event.timestamp), "Critical": event.critical, "HeavyHit": event.heavy_hit,
        }

    def _update_record(self, key: str, event: CombatEvent) -> None:
        current = self.data.get(key)
        if not isinstance(current, dict) or float(current.get("Value", 0)) < event.amount:
            self.data[key] = self._record(event)

    @staticmethod
    def _hit_key(event: CombatEvent) -> str:
        if event.critical and event.heavy_hit:
            return "Devastating"
        if event.critical:
            return "Critical"
        if event.heavy_hit:
            return "Heavy"
        return "Normal"

    def _add_total(self, collection_key: str, amount: float) -> float:
        mapping = self.data[collection_key]
        log_key = self._log_key()
        actual_key = dict_key_casefold(mapping, log_key) or log_key
        mapping[actual_key] = float(mapping.get(actual_key, 0)) + amount
        return mapping[actual_key]

    def _run_hit_damage(self) -> dict[str, float]:
        mapping = self.data["LogHitDamageTotals"]
        log_key = self._log_key()
        actual_key = dict_key_casefold(mapping, log_key) or log_key
        if actual_key not in mapping or not isinstance(mapping[actual_key], dict):
            mapping[actual_key] = {"Normal": 0.0, "Critical": 0.0, "Heavy": 0.0, "Devastating": 0.0}
        return mapping[actual_key]

    def apply(self, event: CombatEvent) -> None:
        if not is_own_event(event) or event.type not in {"damage", "heal"} or event.amount <= 0:
            return
        if event.sequence is not None:
            if event.sequence in self.sequences_this_read:
                return
            self.sequences_this_read.add(event.sequence)
        if event.event_id:
            if event.event_id in self.ids_this_read:
                return
            self.ids_this_read.add(event.event_id)

        window = self.damage_window if event.type == "damage" else self.healing_window
        window.append((event.timestamp, event.amount))
        while window and event.timestamp - window[0][0] > 60:
            window.popleft()
        rolling = sum(amount for _, amount in window)
        best_key = "BestDamage60" if event.type == "damage" else "BestHealing60"
        best_at_key = best_key + "At"
        if rolling > float(self.data.get(best_key, 0)):
            self.data[best_key] = rolling
            self.data[best_at_key] = timestamp_text(event.timestamp)
            self.dirty = True

        already_counted = self._persisted(event)
        self._checkpoint(event)
        if already_counted:
            self.save_if_due()
            return

        log_key = self._log_key()
        counted = self.data["CountedLogs"]
        if not any(str(item).casefold() == log_key.casefold() for item in counted):
            counted.append(log_key)
            self.data["RunsTracked"] = int(self.data.get("RunsTracked", 0)) + 1

        if event.type == "damage":
            self.data["LifetimeDamage"] = float(self.data.get("LifetimeDamage", 0)) + event.amount
            self._update_record("HighestDamage", event)
            hit_key = self._hit_key(event)
            record_key = {"Normal": "HighestNormalHit", "Critical": "HighestCriticalHit", "Heavy": "HighestHeavyHit", "Devastating": "HighestDevastatingHit"}[hit_key]
            self._update_record(record_key, event)
            run_total = self._add_total("LogDamageTotals", event.amount)
            run_hits = self._run_hit_damage()
            run_hits[hit_key] = float(run_hits.get(hit_key, 0)) + event.amount
            lifetime_hits = self.data["LifetimeHitDamage"]
            lifetime_hits[hit_key] = float(lifetime_hits.get(hit_key, 0)) + event.amount
            if run_total > float(self.data.get("BestRunDamage", 0)):
                self.data["BestRunDamage"] = run_total
                self.data["BestRunDamageAt"] = timestamp_text(event.timestamp)
        else:
            self.data["LifetimeHealing"] = float(self.data.get("LifetimeHealing", 0)) + event.amount
            self._update_record("HighestHealing", event)
            run_total = self._add_total("LogHealingTotals", event.amount)
            if run_total > float(self.data.get("BestRunHealing", 0)):
                self.data["BestRunHealing"] = run_total
                self.data["BestRunHealingAt"] = timestamp_text(event.timestamp)

        if event.event_id:
            ids = self.data["RecentEventIds"]
            ids.append(event.event_id)
            if len(ids) > 5000:
                del ids[:-5000]
        self.data["LastUpdatedUtc"] = timestamp_text(utc_now())
        self.dirty = True
        self.save_if_due()

    def snapshot(self) -> dict[str, Any]:
        self.save_if_due()
        result = dict(self.data)
        result["CurrentRunHitDamage"] = dict(self._run_hit_damage())
        return result

    def save_if_due(self) -> None:
        if self.dirty and utc_now() - self.last_save >= 0.5:
            self.save()

    def save(self, force: bool = False) -> None:
        if not force and not self.dirty:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, self.path)
            self.dirty = False
            self.last_save = utc_now()
        except OSError:
            pass


class AppSettings:
    DEFAULTS = {
        "CombatLogPath": None, "CombatLogFolder": None, "CleanupOldCombatLogs": False,
        "FollowGameWindow": True, "ThemeColorHex": "#10151D", "WindowLeft": None, "WindowTop": None,
        "OverlayOpacity": 1.0, "FadeWhenAfk": False, "AfkFadeSeconds": 6.0,
        "IncludeOverkillDamage": False, "WindowWidth": None, "WindowHeight": None, "FontScale": 1.0,
        "CompactMode": False, "NormalWindowWidth": None, "NormalWindowHeight": None,
        "CompactWindowWidth": None, "CompactWindowHeight": None,
    }

    def __init__(self) -> None:
        self.data = dict(self.DEFAULTS)
        try:
            loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self.data.update({key: loaded[key] for key in self.DEFAULTS if key in loaded})
        except (OSError, json.JSONDecodeError):
            pass

    def get(self, key: str) -> Any:
        return self.data.get(key, self.DEFAULTS.get(key))

    def set(self, key: str, value: Any, save: bool = True) -> None:
        self.data[key] = value
        if save:
            self.save()

    def save(self) -> None:
        try:
            SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS_PATH.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        except OSError:
            pass


class CombatLogWatcher:
    LOG_START_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}Z)$", re.IGNORECASE)

    def __init__(self, configured_folder: str | None, cleanup_enabled: bool,
                 event_callback: Callable[[CombatEvent], None], log_callback: Callable[[str], None],
                 status_callback: Callable[[bool, str], None]) -> None:
        self.folder = self._normalize_folder(configured_folder)
        self.cleanup_enabled = cleanup_enabled
        self.event_callback = event_callback
        self.log_callback = log_callback
        self.status_callback = status_callback
        self.resolver = CombatAbilityResolver()
        self.active_path: Path | None = None
        self.position = 0
        self.partial = b""
        self.last_status: tuple[bool, str] | None = None

    @staticmethod
    def _normalize_folder(path: str | None) -> Path | None:
        if not path:
            return None
        candidate = Path(path).expanduser()
        if candidate.is_file():
            candidate = candidate.parent
        try:
            return candidate.resolve()
        except OSError:
            return None

    @staticmethod
    def default_folder() -> Path | None:
        root = LOCAL_APP_DATA / "worldwidewebb"
        candidates = [root / "combat_logs", root / "combat-logs", root / "logs" / "combat", root / "logs", root]
        return next((folder for folder in candidates if folder.is_dir() and CombatLogWatcher.find_newest(folder)), None) or next((folder for folder in candidates if folder.is_dir()), None)

    @staticmethod
    def verified(path: Path) -> bool:
        try:
            with path.open("r", encoding="utf-8-sig", errors="strict") as handle:
                for _ in range(32):
                    line = handle.readline()
                    if not line:
                        break
                    try:
                        root = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(root, dict):
                        continue
                    if str(root.get("event", "")).lower() == "log_header":
                        return True
                    data = root.get("data")
                    if isinstance(data, dict) and str(data.get("format", "")).lower() == "soulbound_combat_log":
                        return True
        except (OSError, UnicodeError):
            pass
        return False

    @staticmethod
    def files(folder: Path) -> list[Path]:
        try:
            return [path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS]
        except OSError:
            return []

    @classmethod
    def find_newest(cls, folder: Path) -> Path | None:
        verified = [path for path in cls.files(folder) if cls.verified(path)]
        try:
            return max(verified, key=lambda path: (path.stat().st_mtime_ns, path.stat().st_ctime_ns, path.name.lower()), default=None)
        except OSError:
            return None

    @classmethod
    def log_start_key(cls, path: Path) -> int:
        match = cls.LOG_START_PATTERN.search(path.stem)
        if match:
            try:
                parsed = datetime.strptime(match.group(1), "%Y-%m-%d_%H-%M-%SZ").replace(tzinfo=timezone.utc)
                return int(parsed.timestamp() * 1_000_000_000)
            except ValueError:
                pass
        try:
            return path.stat().st_ctime_ns
        except OSError:
            return 0

    @classmethod
    def cleanup_old_logs(cls, folder: Path, keep: int = 10) -> int:
        verified = [path for path in cls.files(folder) if cls.verified(path)]
        try:
            verified.sort(key=lambda path: (path.stat().st_mtime_ns, path.stat().st_ctime_ns, path.name.lower()), reverse=True)
        except OSError:
            return 0
        removed = 0
        for path in verified[keep:]:
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
        return removed

    def _status(self, connected: bool, message: str) -> None:
        status = (connected, message)
        if status != self.last_status:
            self.last_status = status
            self.status_callback(connected, message)

    def change_folder(self, folder: str) -> None:
        self.folder = self._normalize_folder(folder)
        self.active_path = None
        self.position = 0
        self.partial = b""

    def poll(self) -> None:
        if self.folder is None:
            self.folder = self.default_folder()
        if self.folder is None or not self.folder.is_dir():
            self._status(False, "Waiting for combat-log folder")
            return
        candidate = self.find_newest(self.folder)
        if self.active_path is None and candidate is None:
            self._status(False, "Waiting for a combat log")
            return
        should_switch = self.active_path is None
        if (self.active_path is not None and candidate is not None
                and str(self.active_path).casefold() != str(candidate).casefold()):
            # The active file can be temporarily empty or unverifiable while the
            # game rewrites it. Never fall back to an older dungeon during that
            # window; switch only when a genuinely newer run filename appears.
            should_switch = self.log_start_key(candidate) > self.log_start_key(self.active_path)
        if should_switch and candidate is not None:
            self.active_path = candidate
            self.position = 0
            self.partial = b""
            self.resolver.reset()
            self.log_callback(str(candidate))
            removed = self.cleanup_old_logs(self.folder, 10) if self.cleanup_enabled else 0
            suffix = f" · cleared {removed} old" if removed else ""
            self._status(True, f"Reading {candidate.name}{suffix}")
        newest = self.active_path
        if newest is None:
            self._status(False, "Waiting for a combat log")
            return
        try:
            size = newest.stat().st_size
            if size < self.position:
                self.position = 0
                self.partial = b""
            with newest.open("rb") as handle:
                handle.seek(self.position)
                chunk = handle.read()
                self.position = handle.tell()
            if chunk:
                parts = (self.partial + chunk).split(b"\n")
                self.partial = parts.pop()
                for raw in parts:
                    self._consume(raw.rstrip(b"\r"))
                if self.partial:
                    try:
                        json.loads(self.partial.decode("utf-8-sig"))
                    except (json.JSONDecodeError, UnicodeError):
                        pass
                    else:
                        self._consume(self.partial)
                        self.partial = b""
            self._status(True, f"Reading {newest.name}")
        except PermissionError:
            self._status(False, "Cannot read combat-log folder")
        except OSError:
            self._status(False, "Combat log temporarily unavailable")
        except UnicodeError:
            self._status(False, "Combat log must be UTF-8")

    def _consume(self, raw: bytes) -> None:
        if not raw.strip():
            return
        try:
            root = json.loads(raw.decode("utf-8-sig"))
        except (json.JSONDecodeError, UnicodeError):
            return
        if not isinstance(root, dict):
            return
        self.resolver.observe(root)
        event = parse_combat_event(root)
        if event is not None:
            self.event_callback(self.resolver.resolve(event))


class WindowsApi:
    HOTKEY_ID = 0x5342
    WM_HOTKEY = 0x0312
    PM_REMOVE = 0x0001
    MOD_ALT = 0x0001
    MOD_SHIFT = 0x0004
    MOD_NOREPEAT = 0x4000
    VK_D = 0x44
    GWL_EXSTYLE = -20
    WS_EX_TRANSPARENT = 0x20

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class MSG(ctypes.Structure):
        _fields_ = [
            ("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint), ("wParam", ctypes.c_size_t),
            ("lParam", ctypes.c_ssize_t), ("time", ctypes.c_uint),
            ("pt_x", ctypes.c_long), ("pt_y", ctypes.c_long), ("lPrivate", ctypes.c_uint),
        ]

    def __init__(self, root: tk.Tk) -> None:
        self.available = os.name == "nt"
        self.root = root
        self.hwnd = 0
        self.hotkey_registered = False
        if not self.available:
            return
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32
        hwnd_type = ctypes.c_void_p
        self.user32.RegisterHotKey.argtypes = [hwnd_type, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
        self.user32.RegisterHotKey.restype = ctypes.c_bool
        self.user32.UnregisterHotKey.argtypes = [hwnd_type, ctypes.c_int]
        self.user32.UnregisterHotKey.restype = ctypes.c_bool
        self.user32.PeekMessageW.argtypes = [ctypes.POINTER(self.MSG), hwnd_type, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
        self.user32.PeekMessageW.restype = ctypes.c_bool
        self.user32.GetWindowLongW.argtypes = [hwnd_type, ctypes.c_int]
        self.user32.GetWindowLongW.restype = ctypes.c_long
        self.user32.SetWindowLongW.argtypes = [hwnd_type, ctypes.c_int, ctypes.c_long]
        self.user32.SetWindowLongW.restype = ctypes.c_long
        self.user32.ShowWindow.argtypes = [hwnd_type, ctypes.c_int]
        self.user32.ShowWindow.restype = ctypes.c_bool
        self.user32.IsWindow.argtypes = [hwnd_type]
        self.user32.IsWindow.restype = ctypes.c_bool
        self.user32.IsWindowVisible.argtypes = [hwnd_type]
        self.user32.IsWindowVisible.restype = ctypes.c_bool
        self.user32.IsIconic.argtypes = [hwnd_type]
        self.user32.IsIconic.restype = ctypes.c_bool
        self.user32.GetWindowThreadProcessId.argtypes = [hwnd_type, ctypes.POINTER(ctypes.c_ulong)]
        self.user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
        self.user32.GetWindowRect.argtypes = [hwnd_type, ctypes.POINTER(self.RECT)]
        self.user32.GetWindowRect.restype = ctypes.c_bool
        self.user32.GetDpiForWindow.argtypes = [hwnd_type]
        self.user32.GetDpiForWindow.restype = ctypes.c_uint
        self.kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
        self.kernel32.OpenProcess.restype = ctypes.c_void_p
        self.kernel32.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
        self.kernel32.QueryFullProcessImageNameW.restype = ctypes.c_bool
        self.kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        self.kernel32.CloseHandle.restype = ctypes.c_bool
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                self.user32.SetProcessDPIAware()
            except Exception:
                pass
        root.update_idletasks()
        self.hwnd = int(root.winfo_id())
        self.hotkey_registered = bool(self.user32.RegisterHotKey(
            self.hwnd, self.HOTKEY_ID, self.MOD_ALT | self.MOD_SHIFT | self.MOD_NOREPEAT, self.VK_D))

    def poll_hotkey(self) -> bool:
        if not self.available or not self.hwnd:
            return False
        message = self.MSG()
        return bool(self.user32.PeekMessageW(ctypes.byref(message), self.hwnd, self.WM_HOTKEY, self.WM_HOTKEY, self.PM_REMOVE))

    def set_click_through(self, enabled: bool) -> None:
        if not self.available or not self.hwnd:
            return
        style = self.user32.GetWindowLongW(self.hwnd, self.GWL_EXSTYLE)
        new_style = style | self.WS_EX_TRANSPARENT if enabled else style & ~self.WS_EX_TRANSPARENT
        self.user32.SetWindowLongW(self.hwnd, self.GWL_EXSTYLE, new_style)

    def minimize(self) -> None:
        if self.available and self.hwnd:
            self.user32.ShowWindow(self.hwnd, 6)
        else:
            self.root.iconify()

    def find_soulbound(self) -> tuple[int, int] | None:
        if not self.available:
            return None
        found: list[tuple[int, int]] = []
        enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        @enum_proc
        def callback(hwnd: int, _lparam: int) -> bool:
            if not self.user32.IsWindowVisible(hwnd):
                return True
            pid = ctypes.c_ulong()
            self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            process = self.kernel32.OpenProcess(0x1000, False, pid.value)
            if not process:
                return True
            try:
                size = ctypes.c_ulong(2048)
                buffer = ctypes.create_unicode_buffer(size.value)
                if self.kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
                    if Path(buffer.value).stem.casefold() == "soulbound":
                        found.append((int(hwnd), int(pid.value)))
                        return False
            finally:
                self.kernel32.CloseHandle(process)
            return True

        self.user32.EnumWindows(callback, 0)
        return found[0] if found else None

    def window_rect(self, hwnd: int) -> tuple[int, int, int, int] | None:
        if not self.available or not self.user32.IsWindow(hwnd) or self.user32.IsIconic(hwnd):
            return None
        rect = self.RECT()
        if not self.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        dpi = self.user32.GetDpiForWindow(hwnd) or 96
        scale = dpi / 96.0
        return (round(rect.left / scale), round(rect.top / scale), round(rect.right / scale), round(rect.bottom / scale))

    def close(self) -> None:
        if self.available and self.hotkey_registered:
            self.user32.UnregisterHotKey(self.hwnd, self.HOTKEY_ID)


def color_tuple(hex_color: str) -> tuple[int, int, int]:
    text = hex_color.strip().lstrip("#")
    if len(text) != 6:
        raise ValueError("Expected RRGGBB")
    return tuple(int(text[index:index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]


def color_hex(color: tuple[int, int, int]) -> str:
    return "#%02X%02X%02X" % color


def mix_color(source: tuple[int, int, int], target: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    return tuple(round(a + (b - a) * amount) for a, b in zip(source, target))  # type: ignore[return-value]


class MeterApp:
    FONT = "Segoe UI"
    NORMAL_WINDOW_SIZE = (360, 650)
    COMPACT_WINDOW_SIZE = (520, 325)
    NORMAL_MIN_SIZE = (320, 560)
    COMPACT_MIN_SIZE = (420, 300)

    def __init__(self, log_override: str | None = None, smoke_seconds: float | None = None) -> None:
        self.settings = AppSettings()
        self.session = CombatSession()
        self.records = FlexRecordStore()
        configured = log_override or self.settings.get("CombatLogFolder") or self.settings.get("CombatLogPath")
        self.process_status = "Looking for Soulbound…"
        self.process_connected = False
        self.log_status = "Waiting for combat log"
        self.log_connected = False
        self.current_map = "Waiting for dungeon"
        self.game_window: int | None = None
        self.game_pid: int | None = None
        self.last_process_poll = 0.0
        self.locked = False
        try:
            configured_opacity = float(self.settings.get("OverlayOpacity"))
        except (TypeError, ValueError):
            configured_opacity = 1.0
        self.current_opacity = min(1.0, max(0.2, configured_opacity))
        self.settings.data["OverlayOpacity"] = self.current_opacity
        try:
            configured_font_scale = float(self.settings.get("FontScale"))
        except (TypeError, ValueError):
            configured_font_scale = 1.0
        self.font_scale = min(1.5, max(0.8, configured_font_scale))
        self.settings.data["FontScale"] = self.font_scale
        self.current_view = "meter"
        self.compact_mode = bool(self.settings.get("CompactMode"))
        self.closed = False
        self.theme_roles: list[tuple[tk.Widget, str | None, str | None]] = []
        self._font_targets: list[tuple[tk.Widget, int, str]] = []
        self.metric_cards: list[tk.Frame] = []
        self.flex_cards: list[tk.Frame] = []
        self.flex_card_details: list[tk.Label] = []
        self.chance_boxes: list[tk.Frame] = []
        self.run_high_boxes: list[tk.Frame] = []
        self.ability_rows: list[dict[str, Any]] = []
        self._ability_tooltip: tk.Toplevel | None = None
        self._ability_tooltip_row: dict[str, Any] | None = None
        self._ability_tooltip_hide_job: str | None = None
        self._updating_theme = False
        self._drag_start: tuple[int, int, int, int] | None = None
        self._resize_start: tuple[int, int, int, int] | None = None
        self._minimized = False
        self._restore_binding: str | None = None
        self._settings_wheel_binding: str | None = None
        self._app_icon: tk.PhotoImage | None = None
        self._brand_sheet: tk.PhotoImage | None = None
        self._brand_frames_normal: list[tk.PhotoImage] = []
        self._brand_frames_compact: list[tk.PhotoImage] = []
        self._brand_frame_index = 0
        self._brand_animation_job: str | None = None

        if os.name == "nt":
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TundraWooK.DpsMeter")
            except (AttributeError, OSError):
                pass
        self.root = tk.Tk()
        self.root.title("DPS Meter")
        self._load_app_icon()
        self.root.geometry(self._initial_geometry())
        self.root.minsize(*self._active_min_size())
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", self.current_opacity)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Configure>", lambda _event: self._position_settings_entry())

        self.outer = tk.Frame(self.root, highlightthickness=1)
        self.outer.pack(fill="both", expand=True, padx=7, pady=7)
        self.content = self.role(tk.Frame(self.outer), "bg", None)
        self.content.pack(fill="both", expand=True, padx=14, pady=11)
        self._build_header()
        self._load_brand_animation()
        self.view_host = self.role(tk.Frame(self.content), "bg", None)
        self.view_host.pack(fill="both", expand=True)
        self._build_meter_view()
        self._build_flex_view()
        self._build_settings_view()
        self._build_credit_and_grip()
        self._load_icons()
        self.apply_theme(str(self.settings.get("ThemeColorHex") or "#10151D"), save=False)
        self._apply_compact_mode(initial=True)

        self.watcher = CombatLogWatcher(
            configured, bool(self.settings.get("CleanupOldCombatLogs")), self._on_combat_event,
            self._on_active_log, self._on_log_status,
        )
        if self.watcher.folder:
            self.settings.set("CombatLogFolder", str(self.watcher.folder))
        self.win = WindowsApi(self.root)
        self.find_and_follow(force=True)
        self.root.after(20, self.tick)
        if smoke_seconds:
            self.root.after(max(100, round(smoke_seconds * 1000)), self.close)

    def _initial_geometry(self) -> str:
        width, height = self._configured_size(self.compact_mode)
        left = self.settings.get("WindowLeft")
        top = self.settings.get("WindowTop")
        if not self.settings.get("FollowGameWindow") and isinstance(left, (int, float)) and isinstance(top, (int, float)):
            return f"{width}x{height}+{round(left)}+{round(top)}"
        return f"{width}x{height}+40+40"

    def _active_min_size(self) -> tuple[int, int]:
        return self.COMPACT_MIN_SIZE if self.compact_mode else self.NORMAL_MIN_SIZE

    @staticmethod
    def _mode_size_keys(compact: bool) -> tuple[str, str]:
        return ("CompactWindowWidth", "CompactWindowHeight") if compact else ("NormalWindowWidth", "NormalWindowHeight")

    def _configured_size(self, compact: bool) -> tuple[int, int]:
        width_key, height_key = self._mode_size_keys(compact)
        default_width, default_height = self.COMPACT_WINDOW_SIZE if compact else self.NORMAL_WINDOW_SIZE
        min_width, min_height = self.COMPACT_MIN_SIZE if compact else self.NORMAL_MIN_SIZE
        width_raw = self.settings.get(width_key)
        height_raw = self.settings.get(height_key)
        if not compact:
            width_raw = width_raw if isinstance(width_raw, (int, float)) else self.settings.get("WindowWidth")
            height_raw = height_raw if isinstance(height_raw, (int, float)) else self.settings.get("WindowHeight")
        width = max(min_width, round(width_raw)) if isinstance(width_raw, (int, float)) else default_width
        height = max(min_height, round(height_raw)) if isinstance(height_raw, (int, float)) else default_height
        return min(self.root.winfo_screenwidth(), width), min(self.root.winfo_screenheight(), height)

    def _scaled_font_size(self, base_size: int) -> int:
        adjusted = base_size
        if self.compact_mode:
            if base_size <= 7:
                adjusted = base_size + 1
            elif base_size >= 18:
                adjusted = base_size - 5
            elif base_size >= 15:
                adjusted = base_size - 2
            elif base_size >= 11:
                adjusted = base_size - 1
        return max(6, round(adjusted * self.font_scale))

    def _register_font(self, widget: tk.Widget, size: int, weight: str = "normal") -> None:
        self._font_targets.append((widget, size, weight))

    def _apply_font_scale(self) -> None:
        for widget, base_size, weight in self._font_targets:
            try:
                widget.configure(font=(self.FONT, self._scaled_font_size(base_size), weight))
            except tk.TclError:
                continue

    def role(self, widget: tk.Widget, background: str | None = None, foreground: str | None = None) -> tk.Widget:
        self.theme_roles.append((widget, background, foreground))
        return widget

    def label(self, parent: tk.Misc, text: str = "", size: int = 10, weight: str = "normal",
              foreground: str = "text", **kwargs: Any) -> tk.Label:
        widget = tk.Label(parent, text=text, font=(self.FONT, self._scaled_font_size(size), weight), borderwidth=0, **kwargs)
        self._register_font(widget, size, weight)
        return self.role(widget, "bg", foreground)  # type: ignore[return-value]

    def button(self, parent: tk.Misc, text: str, command: Callable[[], None], width: int | None = None, **kwargs: Any) -> tk.Button:
        widget = tk.Button(parent, text=text, command=command, font=(self.FONT, self._scaled_font_size(9)), relief="flat", borderwidth=1,
                           highlightthickness=0, cursor="hand2", padx=6, pady=4, width=width, **kwargs)
        self._register_font(widget, 9)
        return self.role(widget, "button", "text")  # type: ignore[return-value]

    def panel(self, parent: tk.Misc, **kwargs: Any) -> tk.Frame:
        widget = tk.Frame(parent, highlightthickness=1, **kwargs)
        return self.role(widget, "panel", None)  # type: ignore[return-value]

    def _build_header(self) -> None:
        self.header = self.role(tk.Frame(self.content), "bg", None)
        self.header.pack(fill="x")
        self.header_top = self.role(tk.Frame(self.header), "bg", None)
        self.header_top.pack(fill="x")
        controls = self.role(tk.Frame(self.header_top), "bg", None)
        controls.pack(side="right", anchor="n")
        self.view_button = self.button(controls, "Flex", self.toggle_view, width=4)
        self.view_button.pack(side="left", padx=(0, 4))
        self.button(controls, "⚙", self.show_settings, width=2).pack(side="left", padx=(0, 4))
        self.compact_button = self.button(controls, "Compact", self.toggle_compact_mode, width=7)
        self.compact_button.pack(side="left", padx=(0, 4))
        self.button(controls, "—", self.minimize, width=2).pack(side="left", padx=(0, 4))
        self.button(controls, "×", self.close, width=2).pack(side="left")
        self.header_credit = self.label(self.header_top, "Made by TundraWooK", 7, "bold", "neon")
        self.header_left = self.role(tk.Frame(self.header_top), "bg", None)
        self.header_left.pack(side="left")
        self.brand_logo = self.role(tk.Label(self.header_left, borderwidth=0), "bg", None)
        self.brand_logo.pack(side="left", anchor="n")
        self.map_block = self.role(tk.Frame(self.header), "bg", None)
        self.map_block.pack(fill="x", pady=(2, 0))
        self.map_caption = self.label(self.map_block, "CURRENT MAP", 6, "bold", "muted", anchor="w")
        self.map_caption.pack(side="left")
        self.map_label = self.label(self.map_block, self.current_map, 8, "bold", "text", anchor="w",
                                    justify="left")
        self.map_label.pack(side="left", fill="x", expand=True, padx=(6, 0))
        for widget in (self.header, self.header_top, self.header_left, self.brand_logo, self.map_block, self.map_caption,
                       self.map_label, self.header_credit):
            widget.bind("<ButtonPress-1>", self.start_drag)
            widget.bind("<B1-Motion>", self.drag_window)

    def _load_app_icon(self) -> None:
        try:
            self._app_icon = tk.PhotoImage(data=APP_ICON_PNG_BASE64)
            self.root.iconphoto(True, self._app_icon)
        except tk.TclError:
            self._app_icon = None

    def _load_brand_animation(self) -> None:
        try:
            self._brand_sheet = tk.PhotoImage(data=BRAND_ANIMATION_SHEET_BASE64)
            for index in range(BRAND_ANIMATION_FRAME_COUNT):
                frame = tk.PhotoImage(width=48, height=48)
                left = (index % 10) * 48
                top = (index // 10) * 48
                self.root.tk.call(str(frame), "copy", str(self._brand_sheet),
                                  "-from", left, top, left + 48, top + 48, "-to", 0, 0)
                self._brand_frames_normal.append(frame)
            self._brand_frames_compact = [frame.subsample(3, 3).zoom(2, 2) for frame in self._brand_frames_normal]
        except tk.TclError:
            self._brand_sheet = None
            self._brand_frames_normal = []
            self._brand_frames_compact = []
            return
        self._animate_brand()

    def _animate_brand(self) -> None:
        if self.closed:
            return
        frames = self._brand_frames_compact if self.compact_mode else self._brand_frames_normal
        if frames:
            self._brand_frame_index %= len(frames)
            self.brand_logo.configure(image=frames[self._brand_frame_index])
            self._brand_frame_index = (self._brand_frame_index + 1) % len(frames)
        self._brand_animation_job = self.root.after(100, self._animate_brand)

    def _build_meter_view(self) -> None:
        self.meter_view = self.role(tk.Frame(self.view_host), "bg", None)
        self.meter_view.pack(fill="both", expand=True, pady=(10, 21))

        self.encounter = self.role(tk.Frame(self.meter_view), "bg", None)
        self.encounter.pack(fill="x", pady=(0, 9))
        self.timer = self.role(tk.Frame(self.encounter), "bg", None)
        self.timer.pack(side="left")
        self.label(self.timer, "COMBAT TIME", 7, "bold", "muted").pack(anchor="w")
        self.duration_label = self.label(self.timer, "00:00", 19, "normal", "text")
        self.duration_label.pack(anchor="w")
        self.state_label = self.label(self.encounter, "IDLE", 8, "bold", "accent", padx=8, pady=5)
        self.state_label.pack(side="right")
        self.chances = self.role(tk.Frame(self.encounter), "bg", None)
        self.chances.pack(side="right", padx=(0, 7))
        self.chance_labels: dict[str, tk.Label] = {}
        for column, (key, title, role) in enumerate((("crit", "CRIT CHANCE", "red"), ("heavy", "HEAVY CHANCE", "orange"), ("dev", "DEV CHANCE", "purple"))):
            box = self.role(tk.Frame(self.chances), "bg", None)
            box.grid(row=0, column=column, padx=4)
            self.label(box, title, 6, foreground="muted").pack()
            value = self.label(box, "0%", 11, "bold", role)
            value.pack()
            self.chance_labels[key] = value
            self.chance_boxes.append(box)

        self.metrics = self.role(tk.Frame(self.meter_view), "bg", None)
        self.metrics.pack(fill="x")
        self.metrics.grid_columnconfigure((0, 1), weight=1, uniform="metrics")
        self.dps_value, self.dps_sub, self.dps_title_label = self._metric_card(self.metrics, 0, 0, "DAMAGE · LAST 30S", "red", True)
        self.damage_value, _, self.damage_title_label = self._metric_card(self.metrics, 0, 1, "DAMAGE", "text", False)
        self.hps_value, self.hps_sub, self.hps_title_label = self._metric_card(self.metrics, 1, 0, "HEALING · LAST 30S", "green", True)
        self.combined = self.panel(self.metrics)
        self.combined.grid(row=1, column=1, sticky="nsew", padx=(4, 0), pady=(4, 0))
        self.healing_box = self.role(tk.Frame(self.combined), "panel", None)
        self.healing_box.pack(side="left", fill="both", expand=True, padx=8, pady=7)
        self.healing_title_label = self.label(self.healing_box, "HEALING", 7, foreground="muted")
        self.healing_title_label.pack(anchor="w")
        self.healing_value = self.label(self.healing_box, "0", 15, "bold", "text")
        self.healing_value.pack(anchor="w")
        self.shield_box = self.role(tk.Frame(self.combined), "panel", None)
        self.shield_box.pack(side="left", fill="both", expand=True, padx=(0, 8), pady=7)
        self.shielding_title_label = self.label(self.shield_box, "SHIELDING", 7, foreground="blue")
        self.shielding_title_label.pack(anchor="w")
        self.shielding_value = self.label(self.shield_box, "0", 15, "bold", "blue")
        self.shielding_value.pack(anchor="w")

        self.run_high = self.panel(self.meter_view)
        self.run_high.pack(fill="x", pady=(10, 0))
        self.label(self.run_high, "RUN HIGH", 6, foreground="muted").pack(side="left", padx=7)
        self.run_high_labels: dict[str, tk.Label] = {}
        for key, title, role in (("crit", "CRIT", "red"), ("heavy", "HEAVY", "orange"), ("dev", "DEVASTATING", "purple")):
            box = self.role(tk.Frame(self.run_high), "panel", None)
            box.pack(side="left", fill="x", expand=True, pady=5)
            self.label(box, title, 6, foreground=role).pack(anchor="w")
            value = self.label(box, "0", 8, "bold", "purple" if key == "dev" else "text")
            value.pack(anchor="w")
            self.run_high_labels[key] = value
            self.run_high_boxes.append(box)

        self.abilities_header = self.role(tk.Frame(self.meter_view), "bg", None)
        self.abilities_header.pack(fill="x", pady=(8, 2))
        self.label(self.abilities_header, "TOP ABILITIES", 7, "bold", "muted").pack(side="left")
        self.label(self.abilities_header, "AMOUNT", 7, "bold", "muted").pack(side="right")
        self.abilities_frame = self.role(tk.Frame(self.meter_view), "bg", None)
        self.abilities_frame.pack(fill="both", expand=True)
        for _ in range(6):
            row = self.role(tk.Frame(self.abilities_frame), "bg", None)
            row.pack(fill="x", pady=2)
            icon_holder = self.role(tk.Frame(row, width=25, height=25), "bg", None)
            icon_holder.pack(side="left", padx=(0, 7))
            icon_holder.pack_propagate(False)
            icon = self.role(tk.Label(icon_holder, borderwidth=0), "bg", None)
            icon.place(relx=0.5, rely=0.5, anchor="center")
            middle = self.role(tk.Frame(row), "bg", None)
            name_line = self.role(tk.Frame(middle), "bg", None)
            name_line.pack(fill="x")
            damage_type = self.label(name_line, "", 6, "bold", "muted", anchor="e")
            damage_type.pack(side="right", padx=(5, 10))
            name = self.label(name_line, "", 8, foreground="text", anchor="w")
            name.pack(side="left", fill="x", expand=True)
            bar = tk.Canvas(middle, height=3, borderwidth=0, highlightthickness=0)
            self.role(bar, "bar_bg", None)
            bar.pack(fill="x", pady=(3, 0), padx=(0, 10))
            amount = self.label(row, "", 8, "bold", "text", anchor="ne")
            amount.pack(side="right", anchor="n")
            middle.pack(side="left", fill="x", expand=True)
            row_info = {
                "frame": row, "icon": icon, "name": name, "damage_type": damage_type,
                "bar": bar, "amount": amount, "icon_holder": icon_holder,
                "percent": 0.0, "segments": {}, "ability": None,
            }
            self.ability_rows.append(row_info)
            for hover_widget in (row, icon_holder, icon, middle, name_line, damage_type, name, bar, amount):
                hover_widget.bind("<Enter>", lambda event, info=row_info: self._show_ability_tooltip(info, event))
                hover_widget.bind("<Leave>", self._schedule_hide_ability_tooltip)

        self.footer = self.role(tk.Frame(self.meter_view), "bg", None)
        self.footer.pack(fill="x", side="bottom", pady=(5, 0))
        self.log_path_label = self.label(self.footer, "Log folder: auto-detect", 6, foreground="dim", anchor="w")
        self.log_path_label.pack(fill="x", pady=(0, 5))
        self.follow_var = tk.BooleanVar(value=bool(self.settings.get("FollowGameWindow")))
        self.follow_check = tk.Checkbutton(self.footer, text="Follow game window", variable=self.follow_var, command=self.follow_changed,
                                           font=(self.FONT, self._scaled_font_size(7)), borderwidth=0, highlightthickness=0, anchor="w")
        self._register_font(self.follow_check, 7)
        self.role(self.follow_check, "bg", "muted")
        self.follow_check.pack(anchor="w", pady=(4, 0))
        self.hotkey_hint = self.label(self.footer, "Alt+Shift+D toggles click-through lock", 6, foreground="dim")
        self.hotkey_hint.pack(anchor="w")
        # Repack the expandable list after the bottom-anchored footer so the
        # footer always reserves its space and ability rows fill the gap.
        self.abilities_frame.pack_forget()
        self.abilities_frame.pack(fill="both", expand=True)

    def _metric_card(self, parent: tk.Misc, row: int, column: int, title: str, value_role: str,
                     has_sub: bool) -> tuple[tk.Label, tk.Label | None, tk.Label]:
        card = self.panel(parent)
        self.metric_cards.append(card)
        card.grid(row=row, column=column, sticky="nsew", padx=(0, 4) if column == 0 else (4, 0), pady=(0, 4) if row == 0 else (4, 0))
        title_label = self.label(card, title, 7, foreground="muted")
        title_label.pack(anchor="w", padx=8, pady=(6, 0))
        value = self.label(card, "0", 15, "bold", value_role)
        value.pack(anchor="w", padx=8)
        sub = None
        if has_sub:
            sub = self.label(card, "0 DPS" if "DAMAGE" in title else "0 HPS", 6, foreground="muted")
            sub.pack(anchor="w", padx=8, pady=(0, 5))
        else:
            self.label(card, "", 6).pack(pady=(0, 5))
        return value, sub, title_label

    def _build_flex_view(self) -> None:
        self.flex_view = self.role(tk.Frame(self.view_host), "bg", None)
        self.flex_top = self.role(tk.Frame(self.flex_view), "bg", None)
        self.flex_top.pack(fill="x", pady=(12, 8))
        self.flex_top_left = self.role(tk.Frame(self.flex_top), "bg", None)
        self.flex_top_left.pack(side="left")
        self.flex_title = self.label(self.flex_top_left, "FLEX RECORDS", 10, "bold", "text")
        self.flex_title.pack(anchor="w")
        self.flex_subtitle = self.label(self.flex_top_left, "Your permanent personal bests", 7, foreground="muted")
        self.flex_subtitle.pack(anchor="w")
        self.flex_saved_label = self.label(self.flex_top, "SAVED LIVE", 7, "bold", "accent")
        self.flex_saved_label.pack(side="right")

        self.flex_grid = self.role(tk.Frame(self.flex_view), "bg", None)
        self.flex_grid.pack(fill="both", expand=True)
        self.flex_grid.grid_columnconfigure((0, 1), weight=1, uniform="flex")
        self.flex_grid.grid_rowconfigure((0, 1, 2), weight=1, uniform="flexrow")
        self.flex_card_values: dict[str, tuple[tk.Label, tk.Label]] = {}
        card_specs = (
            ("big_hit", "BIGGEST HIT", "red"), ("big_heal", "BIGGEST HEAL", "green"),
            ("damage60", "BEST DAMAGE · 60 SEC", "red"), ("healing60", "BEST HEALING · 60 SEC", "green"),
            ("run_damage", "BEST RUN DAMAGE", "red"), ("run_healing", "BEST RUN HEALING", "green"),
        )
        for index, (key, title, value_role) in enumerate(card_specs):
            row, column = divmod(index, 2)
            card = self.panel(self.flex_grid)
            self.flex_cards.append(card)
            card.grid(row=row, column=column, sticky="nsew", padx=(0, 4) if column == 0 else (4, 0), pady=(0, 4) if row == 0 else ((4, 4) if row == 1 else (4, 0)))
            self.label(card, title, 7, foreground="muted").pack(anchor="w", padx=8, pady=(7, 0))
            value = self.label(card, "0", 14, "bold", value_role)
            value.pack(anchor="w", padx=8)
            detail = self.label(card, "No record yet", 6, foreground="muted", anchor="w")
            detail.pack(fill="x", padx=8, pady=(0, 6))
            self.flex_card_details.append(detail)
            self.flex_card_values[key] = (value, detail)

        self.hit_panel = self.panel(self.flex_view)
        self.hit_panel.pack(fill="x", pady=(8, 7))
        self.label(self.hit_panel, "PERSONAL BEST BY HIT TYPE", 6, foreground="muted").pack(anchor="w", padx=8, pady=(6, 3))
        self.hit_row = self.role(tk.Frame(self.hit_panel), "panel", None)
        self.hit_row.pack(fill="x", padx=8, pady=(0, 6))
        self.flex_hit_labels: dict[str, tk.Label] = {}
        for key, title, role in (("normal", "NORMAL", "muted"), ("crit", "CRIT", "red"), ("heavy", "HEAVY", "orange"), ("dev", "DEVASTATING", "purple")):
            box = self.role(tk.Frame(self.hit_row), "panel", None)
            box.pack(side="left", fill="x", expand=True)
            self.label(box, title, 6, foreground=role).pack(anchor="w")
            value = self.label(box, "0", 8, "bold", "purple" if key == "dev" else "text")
            value.pack(anchor="w")
            self.flex_hit_labels[key] = value

        self.lifetime = self.panel(self.flex_view)
        self.lifetime.pack(fill="x")
        self.flex_lifetime_labels: dict[str, tk.Label] = {}
        for key, title in (("damage", "LIFETIME DAMAGE"), ("healing", "LIFETIME HEALING"), ("runs", "RUNS RECORDED")):
            box = self.role(tk.Frame(self.lifetime), "panel", None)
            box.pack(side="left", fill="x", expand=True, padx=8, pady=7)
            self.label(box, title, 6, foreground="muted").pack(anchor="w")
            value = self.label(box, "0", 9, "bold", "text")
            value.pack(anchor="w")
            self.flex_lifetime_labels[key] = value
        self.records_path_label = self.label(self.flex_view, f"Records: {self.records.path}", 6, foreground="dim", anchor="w")
        self.records_path_label.pack(fill="x", pady=(7, 18))

    def _build_settings_view(self) -> None:
        self.settings_view = self.role(tk.Frame(self.outer, highlightthickness=1), "bg", None)
        header = self.role(tk.Frame(self.settings_view), "bg", None)
        header.pack(fill="x", padx=15, pady=(14, 0))
        self.label(header, "APPEARANCE", 10, "bold", "text").pack(side="left")
        self.button(header, "×", self.hide_settings, width=2).pack(side="right")
        settings_scroll_host = self.role(tk.Frame(self.settings_view), "bg", None)
        settings_scroll_host.pack(fill="both", expand=True, pady=(8, 0))
        self.settings_canvas = self.role(tk.Canvas(settings_scroll_host, borderwidth=0, highlightthickness=0), "bg", None)
        self.settings_scrollbar = self.role(tk.Scrollbar(settings_scroll_host, orient="vertical", width=8,
                                                         command=self.settings_canvas.yview), "panel", None)
        self.settings_canvas.configure(yscrollcommand=self.settings_scrollbar.set)
        self.settings_scrollbar.pack(side="right", fill="y")
        self.settings_canvas.pack(side="left", fill="both", expand=True)
        self.settings_body = self.role(tk.Frame(self.settings_canvas), "bg", None)
        self.settings_body_window = self.settings_canvas.create_window((0, 0), window=self.settings_body, anchor="nw")
        self.settings_body.bind("<Configure>", self._sync_settings_scroll_region)
        self.settings_canvas.bind("<Configure>", self._size_settings_body)

        self.label(self.settings_body, "Menu color", 8, foreground="muted").pack(anchor="w", padx=15, pady=(3, 4))
        sliders = self.role(tk.Frame(self.settings_body), "bg", None)
        sliders.pack(fill="x", padx=15)
        self.rgb_vars: dict[str, tk.DoubleVar] = {}
        self.rgb_value_labels: dict[str, tk.Label] = {}
        for row, (key, title) in enumerate((("r", "Red"), ("g", "Green"), ("b", "Blue"))):
            self.label(sliders, title, 8, foreground="text", width=5, anchor="w").grid(row=row, column=0, sticky="w")
            variable = tk.DoubleVar(value=0)
            scale = tk.Scale(sliders, from_=0, to=255, orient="horizontal", showvalue=False, variable=variable,
                             command=lambda _value, channel=key: self.slider_changed(channel), borderwidth=0,
                             highlightthickness=0, sliderlength=14)
            self.role(scale, "bg", "text")
            scale.grid(row=row, column=1, sticky="ew", padx=4, pady=2)
            value = self.label(sliders, "0", 8, foreground="muted", width=3, anchor="e")
            value.grid(row=row, column=2, sticky="e")
            sliders.grid_columnconfigure(1, weight=1)
            self.rgb_vars[key] = variable
            self.rgb_value_labels[key] = value

        hex_row = self.role(tk.Frame(self.settings_body), "bg", None)
        hex_row.pack(fill="x", padx=15, pady=(12, 0))
        self.color_preview = self.role(tk.Frame(hex_row, width=30, height=30, highlightthickness=1), "bg", None)
        self.color_preview.pack(side="left")
        self.color_preview.pack_propagate(False)
        self.hex_var = tk.StringVar(value="#10151D")
        self.hex_entry = tk.Entry(hex_row, textvariable=self.hex_var, font=(self.FONT, self._scaled_font_size(9)), relief="flat", borderwidth=1)
        self._register_font(self.hex_entry, 9)
        self.role(self.hex_entry, "panel", "text")
        self.hex_entry.pack(side="left", fill="x", expand=True, padx=7, ipady=5)
        self.hex_entry.bind("<Return>", lambda _event: self.apply_hex())
        self.button(hex_row, "Apply", self.apply_hex).pack(side="right")

        self.label(self.settings_body, "Presets", 8, foreground="muted").pack(anchor="w", padx=15, pady=(15, 5))
        presets = self.role(tk.Frame(self.settings_body), "bg", None)
        presets.pack(fill="x", padx=15)
        for color in ("#10151D", "#14293A", "#17352F", "#382040", "#40221F", "#3D321A"):
            button = tk.Button(presets, text="", width=3, height=1, background=color, activebackground=color,
                               relief="flat", borderwidth=1, command=lambda value=color: self.apply_theme(value))
            button.pack(side="left", padx=(0, 5))
        self.label(self.settings_body, "Enter any #RRGGBB color or use the RGB sliders. Changes preview instantly and are saved automatically.",
                   7, foreground="muted", justify="left", wraplength=300).pack(anchor="w", padx=15, pady=(8, 0))

        self.label(self.settings_body, "OVERLAY", 7, "bold", "muted").pack(anchor="w", padx=15, pady=(14, 4))
        opacity_row = self.role(tk.Frame(self.settings_body), "bg", None)
        opacity_row.pack(fill="x", padx=15)
        self.label(opacity_row, "Opacity", 8, foreground="text", width=7, anchor="w").grid(row=0, column=0, sticky="w")
        self.opacity_var = tk.DoubleVar(value=self.current_opacity * 100.0)
        opacity_scale = tk.Scale(opacity_row, from_=20, to=100, orient="horizontal", showvalue=False,
                                 variable=self.opacity_var, command=self.opacity_changed, borderwidth=0,
                                 highlightthickness=0, sliderlength=14)
        self.role(opacity_scale, "bg", "text")
        opacity_scale.grid(row=0, column=1, sticky="ew", padx=4)
        self.opacity_value_label = self.label(opacity_row, f"{self.current_opacity * 100:.0f}%", 8,
                                              foreground="muted", width=4, anchor="e")
        self.opacity_value_label.grid(row=0, column=2, sticky="e")
        opacity_row.grid_columnconfigure(1, weight=1)
        font_row = self.role(tk.Frame(self.settings_body), "bg", None)
        font_row.pack(fill="x", padx=15, pady=(3, 0))
        self.label(font_row, "Font size", 8, foreground="text", width=7, anchor="w").grid(row=0, column=0, sticky="w")
        self.font_scale_var = tk.DoubleVar(value=self.font_scale * 100.0)
        font_scale = tk.Scale(font_row, from_=80, to=150, orient="horizontal", showvalue=False,
                              variable=self.font_scale_var, command=self.font_scale_changed, borderwidth=0,
                              highlightthickness=0, sliderlength=14, resolution=5)
        self.role(font_scale, "bg", "text")
        font_scale.grid(row=0, column=1, sticky="ew", padx=4)
        self.font_scale_value_label = self.label(font_row, f"{self.font_scale * 100:.0f}%", 8,
                                                  foreground="muted", width=4, anchor="e")
        self.font_scale_value_label.grid(row=0, column=2, sticky="e")
        font_row.grid_columnconfigure(1, weight=1)
        self.fade_when_afk_var = tk.BooleanVar(value=bool(self.settings.get("FadeWhenAfk")))
        fade_when_afk = tk.Checkbutton(self.settings_body, text="Fade when AFK / outside a dungeon",
                                       variable=self.fade_when_afk_var, command=self.fade_when_afk_changed,
                                       font=(self.FONT, self._scaled_font_size(8)), borderwidth=0, highlightthickness=0, anchor="w")
        self._register_font(fade_when_afk, 8)
        self.role(fade_when_afk, "bg", "text")
        fade_when_afk.pack(anchor="w", padx=15, pady=(2, 0))
        try:
            fade_seconds = min(60.0, max(1.0, float(self.settings.get("AfkFadeSeconds"))))
        except (TypeError, ValueError):
            fade_seconds = 6.0
        self.settings.data["AfkFadeSeconds"] = fade_seconds
        fade_time_row = self.role(tk.Frame(self.settings_body), "bg", None)
        fade_time_row.pack(fill="x", padx=(34, 15), pady=(2, 0))
        self.label(fade_time_row, "Fade time", 7, foreground="text", width=8, anchor="w").grid(row=0, column=0, sticky="w")
        self.afk_fade_seconds_var = tk.DoubleVar(value=fade_seconds)
        fade_time_scale = tk.Scale(fade_time_row, from_=1, to=60, orient="horizontal", showvalue=False,
                                   variable=self.afk_fade_seconds_var, command=self.afk_fade_seconds_changed,
                                   borderwidth=0, highlightthickness=0, sliderlength=14)
        self.role(fade_time_scale, "bg", "text")
        fade_time_scale.grid(row=0, column=1, sticky="ew", padx=4)
        self.afk_fade_seconds_label = self.label(fade_time_row, self.format_fade_seconds(fade_seconds), 7,
                                                 foreground="muted", width=6, anchor="e")
        self.afk_fade_seconds_label.grid(row=0, column=2, sticky="e")
        fade_time_row.grid_columnconfigure(1, weight=1)
        self.label(self.settings_body, "Sets how long fading to 8% takes. Combat wakes the meter quickly.",
                   7, foreground="muted", justify="left", wraplength=290).pack(anchor="w", padx=34, pady=(1, 0))

        self.label(self.settings_body, "DAMAGE", 7, "bold", "muted").pack(anchor="w", padx=15, pady=(12, 5))
        self.include_overkill_var = tk.BooleanVar(value=bool(self.settings.get("IncludeOverkillDamage")))
        include_overkill = tk.Checkbutton(self.settings_body, text="Include overkill damage",
                                          variable=self.include_overkill_var, command=self.include_overkill_changed,
                                          font=(self.FONT, self._scaled_font_size(8)), borderwidth=0, highlightthickness=0, anchor="w")
        self._register_font(include_overkill, 8)
        self.role(include_overkill, "bg", "text")
        include_overkill.pack(anchor="w", padx=15)
        self.label(self.settings_body, "Off matches Gearforge using actual enemy health removed. Flex records keep full hit values.",
                   7, foreground="muted", justify="left", wraplength=290).pack(anchor="w", padx=34, pady=(3, 0))
        self.label(self.settings_body, "COMBAT LOGS", 7, "bold", "muted").pack(anchor="w", padx=15, pady=(12, 5))
        self.cleanup_var = tk.BooleanVar(value=bool(self.settings.get("CleanupOldCombatLogs")))
        cleanup = tk.Checkbutton(self.settings_body, text="Delete verified old combat logs; keep newest 10",
                                 variable=self.cleanup_var, command=self.cleanup_changed, font=(self.FONT, self._scaled_font_size(8)),
                                 borderwidth=0, highlightthickness=0, anchor="w", justify="left")
        self._register_font(cleanup, 8)
        self.role(cleanup, "bg", "text")
        cleanup.pack(anchor="w", padx=15)
        self.label(self.settings_body, "Only files containing a Soulbound combat-log header are eligible.", 7,
                   foreground="muted", justify="left", wraplength=290).pack(anchor="w", padx=34, pady=(3, 0))
        bottom = self.role(tk.Frame(self.settings_body), "bg", None)
        bottom.pack(fill="x", padx=15, pady=15)
        self.button(bottom, "Default color", lambda: self.apply_theme("#10151D")).pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.button(bottom, "Done", self.hide_settings).pack(side="left", fill="x", expand=True, padx=(4, 0))

    def _build_credit_and_grip(self) -> None:
        self.credit = self.label(self.outer, "Made by TundraWooK", 6, "bold", "neon")
        self.credit.place(relx=1.0, rely=1.0, x=-18, y=-8, anchor="se")
        self.grip = self.label(self.outer, "◢", 8, foreground="muted", cursor="size_nw_se")
        self.grip.place(relx=1.0, rely=1.0, x=-1, y=-1, anchor="se")
        self.grip.bind("<ButtonPress-1>", self.start_resize)
        self.grip.bind("<B1-Motion>", self.resize_window)
        self.grip.bind("<ButtonRelease-1>", self.finish_resize)

    def _load_icons(self) -> None:
        self.icons: dict[str, tk.PhotoImage] = {}
        for name, encoded in ICON_DATA.items():
            try:
                image = tk.PhotoImage(data=encoded)
                self.icons[name] = image.subsample(2, 2)
            except tk.TclError:
                continue

    def apply_theme(self, value: str, save: bool = True) -> None:
        try:
            base = color_tuple(value)
        except (ValueError, TypeError):
            return
        luminance = (0.2126 * base[0] + 0.7152 * base[1] + 0.0722 * base[2]) / 255.0
        primary = (16, 20, 25) if luminance > 0.58 else (244, 247, 251)
        target = (0, 0, 0) if luminance > 0.58 else (255, 255, 255)
        self.colors = {
            "bg": color_hex(base), "panel": color_hex(mix_color(base, target, 0.08 if luminance > 0.58 else 0.07)),
            "border": color_hex(mix_color(base, target, 0.34 if luminance > 0.58 else 0.25)),
            "button": color_hex(mix_color(base, target, 0.13 if luminance > 0.58 else 0.12)),
            "accent": color_hex(mix_color(base, (0, 0, 0) if luminance > 0.58 else (255, 255, 255), 0.52)),
            "text": color_hex(primary), "muted": color_hex(mix_color(primary, base, 0.42)),
            "dim": "#687484", "neutral": "#66717F", "green": "#6CE5C1", "red": "#FF7C75",
            "orange": "#FFB75E", "purple": "#B46CFF", "blue": "#72A7FF", "neon": "#39FF88",
            "bar_bg": "#242C37", "bar": "#6C93E5",
        }
        self.root.configure(background=self.colors["bg"])
        self.outer.configure(background=self.colors["bg"], highlightbackground=self.colors["border"])
        for widget, background, foreground in self.theme_roles:
            try:
                options: dict[str, Any] = {}
                if background:
                    options["background"] = self.colors[background]
                    if isinstance(widget, (tk.Button, tk.Checkbutton, tk.Scale)):
                        options["activebackground"] = self.colors[background]
                    if isinstance(widget, tk.Checkbutton):
                        options["selectcolor"] = self.colors["panel"]
                    if isinstance(widget, tk.Frame) and int(widget.cget("highlightthickness") or 0) > 0:
                        options["highlightbackground"] = self.colors["border"]
                if foreground and not isinstance(widget, tk.Frame):
                    options["foreground"] = self.colors[foreground]
                    if isinstance(widget, (tk.Button, tk.Checkbutton, tk.Scale)):
                        options["activeforeground"] = self.colors[foreground]
                widget.configure(**options)
            except (tk.TclError, TypeError):
                pass
        self.color_preview.configure(background=color_hex(base), highlightbackground=self.colors["border"])
        self.settings_scrollbar.configure(background=self.colors["panel"], activebackground=self.colors["button"],
                                          troughcolor=self.colors["bg"])
        self._updating_theme = True
        for key, component in zip(("r", "g", "b"), base):
            self.rgb_vars[key].set(component)
            self.rgb_value_labels[key].configure(text=str(component))
        self.hex_var.set(color_hex(base))
        self._updating_theme = False
        self.settings.data["ThemeColorHex"] = color_hex(base)
        if save:
            self.settings.save()
        self._redraw_bars()

    def slider_changed(self, _channel: str) -> None:
        if self._updating_theme:
            return
        components = tuple(round(self.rgb_vars[key].get()) for key in ("r", "g", "b"))
        for key, component in zip(("r", "g", "b"), components):
            self.rgb_value_labels[key].configure(text=str(component))
        self.apply_theme(color_hex(components))  # type: ignore[arg-type]

    def apply_hex(self) -> None:
        try:
            color_tuple(self.hex_var.get())
        except ValueError:
            messagebox.showerror("Invalid color", "Enter a color in #RRGGBB format.", parent=self.root)
            return
        self.apply_theme(self.hex_var.get())

    def show_settings(self) -> None:
        if self.locked:
            self.toggle_lock()
        self.current_opacity = min(1.0, max(0.2, float(self.settings.get("OverlayOpacity") or 1.0)))
        self.root.attributes("-alpha", self.current_opacity)
        self.settings_view.place(x=0, y=0, relwidth=1, relheight=1)
        self.settings_view.lift()
        self.credit.lift()
        self.grip.lift()
        if self._settings_wheel_binding is None:
            self._settings_wheel_binding = self.root.bind("<MouseWheel>", self._scroll_settings, add="+")

    def hide_settings(self) -> None:
        self.settings_view.place_forget()
        if self._settings_wheel_binding is not None:
            self.root.unbind("<MouseWheel>", self._settings_wheel_binding)
            self._settings_wheel_binding = None

    def _sync_settings_scroll_region(self, _event: tk.Event | None = None) -> None:
        bounds = self.settings_canvas.bbox("all")
        if bounds is not None:
            self.settings_canvas.configure(scrollregion=bounds)

    def _size_settings_body(self, event: tk.Event) -> None:
        self.settings_canvas.itemconfigure(self.settings_body_window, width=max(1, event.width))

    def _scroll_settings(self, event: tk.Event) -> str:
        direction = -1 if event.delta > 0 else 1
        self.settings_canvas.yview_scroll(direction * 3, "units")
        return "break"

    def _position_settings_entry(self) -> None:
        pass

    def _on_combat_event(self, event: CombatEvent) -> None:
        self.session.apply(live_damage_event(event, bool(self.settings.get("IncludeOverkillDamage"))))
        # Flex records intentionally keep the full post-mitigation hit so a
        # personal best is not capped by the target's remaining health.
        self.records.apply(event)

    def _on_active_log(self, path: str) -> None:
        self.session.reset()
        self.records.begin_log(path)
        self.current_map = map_name_from_log_path(path)

    def _on_log_status(self, connected: bool, message: str) -> None:
        self.log_connected = connected
        self.log_status = message

    def reset_session(self) -> None:
        self.session.reset()
        self.refresh()

    def pick_log_folder(self) -> None:
        initial = str(self.watcher.folder) if self.watcher.folder and self.watcher.folder.is_dir() else str(LOCAL_APP_DATA)
        selected = filedialog.askdirectory(title="Select the Soulbound combat-log folder", initialdir=initial, parent=self.root)
        if not selected:
            return
        self.watcher.change_folder(selected)
        self.settings.data["CombatLogFolder"] = str(Path(selected).resolve())
        self.settings.data["CombatLogPath"] = None
        self.settings.save()
        self.log_path_label.configure(text=f"Log folder: {selected}")

    def cleanup_changed(self) -> None:
        enabled = bool(self.cleanup_var.get())
        self.settings.set("CleanupOldCombatLogs", enabled)
        self.watcher.cleanup_enabled = enabled
        if enabled and self.watcher.folder:
            removed = self.watcher.cleanup_old_logs(self.watcher.folder, 10)
            if removed:
                self.log_status = f"Cleared {removed} old combat logs"

    def include_overkill_changed(self) -> None:
        enabled = bool(self.include_overkill_var.get())
        self.settings.set("IncludeOverkillDamage", enabled)
        self.session.reset()
        if self.watcher.active_path is not None:
            self.watcher.position = 0
            self.watcher.partial = b""
            self.watcher.resolver.reset()
            self.log_status = "Recalculating damage totals..."
        self.refresh()

    def opacity_changed(self, value: str) -> None:
        try:
            percent = min(100.0, max(20.0, float(value)))
        except (TypeError, ValueError):
            return
        self.opacity_value_label.configure(text=f"{percent:.0f}%")
        self.current_opacity = percent / 100.0
        self.settings.set("OverlayOpacity", self.current_opacity)
        self.root.attributes("-alpha", self.current_opacity)

    def font_scale_changed(self, value: str) -> None:
        try:
            percent = min(150.0, max(80.0, float(value)))
        except (TypeError, ValueError):
            return
        self.font_scale = percent / 100.0
        self.font_scale_value_label.configure(text=f"{percent:.0f}%")
        self.settings.set("FontScale", self.font_scale)
        self._apply_font_scale()

    def fade_when_afk_changed(self) -> None:
        self.settings.set("FadeWhenAfk", bool(self.fade_when_afk_var.get()))
        self.refresh()

    @staticmethod
    def format_fade_seconds(seconds: float) -> str:
        rounded = round(seconds)
        return "1 sec" if rounded == 1 else f"{rounded} sec"

    def afk_fade_seconds_changed(self, value: str) -> None:
        try:
            seconds = float(round(min(60.0, max(1.0, float(value)))))
        except (TypeError, ValueError):
            return
        self.afk_fade_seconds_label.configure(text=self.format_fade_seconds(seconds))
        self.settings.set("AfkFadeSeconds", seconds)

    def follow_changed(self) -> None:
        enabled = bool(self.follow_var.get())
        self.settings.set("FollowGameWindow", enabled)
        if enabled:
            self.find_and_follow(force=True)

    def toggle_view(self) -> None:
        if self.current_view == "meter":
            self.meter_view.pack_forget()
            self.flex_view.pack(fill="both", expand=True)
            self.current_view = "flex"
            self.view_button.configure(text="Meter")
        else:
            self.flex_view.pack_forget()
            self.meter_view.pack(fill="both", expand=True, pady=(4, 6) if self.compact_mode else (10, 21))
            self.current_view = "meter"
            self.view_button.configure(text="Flex")
        self.refresh()

    def _sync_compact_button_text(self) -> None:
        self.compact_button.configure(text="Normal" if self.compact_mode else "Compact")

    @staticmethod
    def _set_packed(widget: tk.Widget, visible: bool, **pack_options: Any) -> None:
        if visible:
            if widget.winfo_manager():
                widget.pack_configure(**pack_options)
            else:
                widget.pack(**pack_options)
        elif widget.winfo_manager():
            widget.pack_forget()

    def _apply_compact_mode(self, initial: bool = False) -> None:
        self._apply_font_scale()
        outer_pad = 3 if self.compact_mode else 7
        self.outer.pack_configure(padx=outer_pad, pady=outer_pad)
        self.content.pack_configure(padx=6 if self.compact_mode else 14, pady=5 if self.compact_mode else 11)
        if self.meter_view.winfo_manager():
            self.meter_view.pack_configure(pady=(4, 6) if self.compact_mode else (10, 21))

        if self.compact_mode:
            self._set_packed(self.map_caption, False)
            self._set_packed(self.footer, False)
            self._set_packed(self.header_credit, True, side="right", padx=(0, 8))
            self.credit.place_forget()
        else:
            self._set_packed(self.map_caption, True, side="left")
            self._set_packed(self.footer, True, fill="x", side="bottom", pady=(5, 0))
            self._set_packed(self.header_credit, False)
            self.credit.place(relx=1.0, rely=1.0, x=-18, y=-8, anchor="se")

        self.abilities_frame.pack_forget()
        self.abilities_frame.pack(fill="both", expand=True)
        self.encounter.pack_configure(pady=(0, 3) if self.compact_mode else (0, 9))
        self.state_label.configure(padx=5 if self.compact_mode else 8, pady=2 if self.compact_mode else 5)
        self.chances.pack_configure(padx=(0, 3) if self.compact_mode else (0, 7))
        for box in self.chance_boxes:
            box.grid_configure(padx=2 if self.compact_mode else 4)

        self.dps_title_label.configure(text="DAMAGE 30S" if self.compact_mode else "DAMAGE · LAST 30S")
        self.damage_title_label.configure(text="TOTAL" if self.compact_mode else "DAMAGE")
        self.hps_title_label.configure(text="HEAL 30S" if self.compact_mode else "HEALING · LAST 30S")
        self.healing_title_label.configure(text="H" if self.compact_mode else "HEALING")
        self.shielding_title_label.configure(text="S" if self.compact_mode else "SHIELDING")

        if self.compact_mode:
            for column in range(4):
                self.metrics.grid_columnconfigure(column, weight=1, uniform="metrics")
            self.metric_cards[0].grid_configure(row=0, column=0, padx=(0, 2), pady=0)
            self.metric_cards[1].grid_configure(row=0, column=1, padx=2, pady=0)
            self.metric_cards[2].grid_configure(row=0, column=2, padx=2, pady=0)
            self.combined.grid_configure(row=0, column=3, padx=(2, 0), pady=0)
        else:
            for column in range(4):
                self.metrics.grid_columnconfigure(column, weight=1 if column < 2 else 0,
                                                   uniform="metrics" if column < 2 else "")
            self.metric_cards[0].grid_configure(row=0, column=0, padx=(0, 4), pady=(0, 4))
            self.metric_cards[1].grid_configure(row=0, column=1, padx=(4, 0), pady=(0, 4))
            self.metric_cards[2].grid_configure(row=1, column=0, padx=(0, 4), pady=(4, 0))
            self.combined.grid_configure(row=1, column=1, padx=(4, 0), pady=(4, 0))

        for card in self.metric_cards:
            labels = [child for child in card.winfo_children() if isinstance(child, tk.Label)]
            if len(labels) >= 2:
                labels[0].pack_configure(padx=5 if self.compact_mode else 8,
                                         pady=(3, 0) if self.compact_mode else (6, 0))
                labels[1].pack_configure(padx=5 if self.compact_mode else 8)
            if len(labels) >= 3:
                labels[2].pack_configure(padx=5 if self.compact_mode else 8,
                                         pady=(0, 3) if self.compact_mode else (0, 5))

        self.healing_box.pack_configure(padx=5 if self.compact_mode else 8, pady=4 if self.compact_mode else 7)
        self.shield_box.pack_configure(padx=(0, 5) if self.compact_mode else (0, 8),
                                       pady=4 if self.compact_mode else 7)
        self.run_high.pack_configure(pady=(4, 0) if self.compact_mode else (10, 0))
        for box in self.run_high_boxes:
            box.pack_configure(pady=3 if self.compact_mode else 5)
        self.abilities_header.pack_configure(pady=(4, 1) if self.compact_mode else (8, 2))

        if self.compact_mode:
            self.flex_top.pack_configure(pady=(3, 4))
            self._set_packed(self.flex_subtitle, False)
            self._set_packed(self.flex_saved_label, False)
        else:
            self.flex_top.pack_configure(pady=(12, 8))
            self._set_packed(self.flex_subtitle, True, anchor="w")
            self._set_packed(self.flex_saved_label, True, side="right")

        compact_columns = 3 if self.compact_mode else 2
        compact_rows = 2 if self.compact_mode else 3
        for column in range(3):
            self.flex_grid.grid_columnconfigure(column, weight=1 if column < compact_columns else 0, uniform="flex")
        for row_index in range(3):
            self.flex_grid.grid_rowconfigure(row_index, weight=1 if row_index < compact_rows else 0, uniform="flexrow")
        for index, card in enumerate(self.flex_cards):
            row_index, column = divmod(index, compact_columns) if self.compact_mode else divmod(index, 2)
            if self.compact_mode:
                pady = (0, 2) if row_index == 0 else (2, 0)
                padx = (0, 2) if column == 0 else (2, 2) if column == 1 else (2, 0)
            else:
                pady = (0, 4) if row_index == 0 else ((4, 4) if row_index == 1 else (4, 0))
                padx = (0, 4) if column == 0 else (4, 0)
            card.grid_configure(row=row_index, column=column, padx=padx, pady=pady)
            labels = [child for child in card.winfo_children() if isinstance(child, tk.Label)]
            if len(labels) >= 2:
                labels[0].pack_configure(padx=5 if self.compact_mode else 8,
                                         pady=(3, 0) if self.compact_mode else (7, 0))
                labels[1].pack_configure(padx=5 if self.compact_mode else 8)
        for detail in self.flex_card_details:
            self._set_packed(detail, not self.compact_mode, fill="x", padx=8, pady=(0, 6))

        self.hit_panel.pack_configure(pady=(4, 4) if self.compact_mode else (8, 7))
        self.hit_row.pack_configure(padx=5 if self.compact_mode else 8,
                                    pady=(0, 4) if self.compact_mode else (0, 6))
        for child in self.lifetime.winfo_children():
            if isinstance(child, tk.Frame):
                child.pack_configure(padx=5 if self.compact_mode else 8, pady=4 if self.compact_mode else 7)
        self._set_packed(self.records_path_label, not self.compact_mode, fill="x", pady=(7, 18))

        icon_size = 18 if self.compact_mode else 25
        for row in self.ability_rows:
            row["frame"].pack_configure(pady=1 if self.compact_mode else 2)
            row["icon_holder"].configure(width=icon_size, height=icon_size)
            row["bar"].configure(height=2 if self.compact_mode else 3)
            row["icon_holder"].pack_configure(padx=(0, 4) if self.compact_mode else (0, 7))
            row["bar"].pack_configure(padx=(0, 6) if self.compact_mode else (0, 10),
                                      pady=(2, 0) if self.compact_mode else (3, 0))

        self.root.minsize(*self._active_min_size())
        self.root.update_idletasks()
        min_width, min_height = self._active_min_size()
        current_width, current_height = self.root.winfo_width(), self.root.winfo_height()
        if initial or current_width < min_width or current_height < min_height:
            self.root.geometry(f"{max(min_width, current_width)}x{max(min_height, current_height)}+"
                               f"{self.root.winfo_x()}+{self.root.winfo_y()}")
        self._sync_compact_button_text()
        self._redraw_bars()

    def toggle_compact_mode(self) -> None:
        self._store_window_size()
        self.compact_mode = not self.compact_mode
        self.settings.data["CompactMode"] = self.compact_mode
        width, height = self._configured_size(self.compact_mode)
        self.root.geometry(f"{width}x{height}+{self.root.winfo_x()}+{self.root.winfo_y()}")
        self.settings.save()
        self._apply_compact_mode()
        self.refresh()

    @staticmethod
    def _record_detail(record: Any) -> str:
        if not isinstance(record, dict):
            return "No record yet"
        flags = " · DEV" if record.get("Critical") and record.get("HeavyHit") else " · CRIT" if record.get("Critical") else " · HEAVY" if record.get("HeavyHit") else ""
        return f"{record.get('AbilityName') or 'Unknown'}{flags}"

    def refresh(self) -> None:
        snapshot = self.session.snapshot()
        self._update_overlay_opacity(bool(snapshot["in_run"]))
        total_seconds = max(0, round(snapshot["duration"]))
        self.duration_label.configure(text=f"{(total_seconds // 60) % 60:02d}:{total_seconds % 60:02d}")
        self.state_label.configure(text="ACTIVE" if snapshot["active"] else "IDLE")
        self.damage_value.configure(text=format_number(snapshot["damage"]))
        self.healing_value.configure(text=format_number(snapshot["healing"]))
        self.shielding_value.configure(text=format_number(snapshot["shielding"]))
        self.dps_value.configure(text=format_number(snapshot["dps"] * 30))
        self.dps_sub.configure(text=f"{format_number(snapshot['dps'])} DPS")
        self.hps_value.configure(text=format_number(snapshot["hps"] * 30))
        self.hps_sub.configure(text=f"{format_number(snapshot['hps'])} HPS")
        self.chance_labels["crit"].configure(text=format_rate(snapshot["crit_rate"]))
        self.chance_labels["heavy"].configure(text=format_rate(snapshot["heavy_rate"]))
        self.chance_labels["dev"].configure(text=format_rate(snapshot["dev_rate"]))
        self.run_high_labels["crit"].configure(text=format_number(snapshot["highest_crit"]))
        self.run_high_labels["heavy"].configure(text=format_number(snapshot["highest_heavy"]))
        self.run_high_labels["dev"].configure(text=format_number(snapshot["highest_dev"]))

        abilities = snapshot["abilities"]
        for index, row in enumerate(self.ability_rows):
            if index >= len(abilities):
                if self._ability_tooltip_row is row:
                    self._hide_ability_tooltip()
                row["frame"].pack_forget()
                row["ability"] = None
                continue
            if not row["frame"].winfo_manager():
                row["frame"].pack(fill="x", pady=1 if self.compact_mode else 2)
            ability = abilities[index]
            row["name"].configure(text=ability["name"])
            row["damage_type"].configure(text=ability["damage_type"])
            row["amount"].configure(text=format_number(ability["amount"]))
            row["percent"] = ability["percent"]
            row["segments"] = ability["segments"]
            row["ability"] = ability
            icon = self.icons.get(normalize_ability(ability["name"]))
            row["icon"].configure(image=icon or "")
        self._redraw_bars()

        flex = self.records.snapshot()
        cards = {
            "big_hit": (flex.get("HighestDamage"), flex.get("HighestDamage")),
            "big_heal": (flex.get("HighestHealing"), flex.get("HighestHealing")),
            "damage60": (flex.get("BestDamage60", 0), flex.get("BestDamage60At")),
            "healing60": (flex.get("BestHealing60", 0), flex.get("BestHealing60At")),
            "run_damage": (flex.get("BestRunDamage", 0), flex.get("BestRunDamageAt")),
            "run_healing": (flex.get("BestRunHealing", 0), flex.get("BestRunHealingAt")),
        }
        for key, (value_source, detail_source) in cards.items():
            value_label, detail_label = self.flex_card_values[key]
            if isinstance(value_source, dict):
                value_label.configure(text=format_number(float(value_source.get("Value", 0))))
                detail_label.configure(text=self._record_detail(detail_source))
            else:
                value_label.configure(text=format_number(float(value_source or 0)))
                detail_label.configure(text=format_date(detail_source if isinstance(detail_source, str) else None))
        record_keys = {"normal": "HighestNormalHit", "crit": "HighestCriticalHit", "heavy": "HighestHeavyHit", "dev": "HighestDevastatingHit"}
        for key, record_key in record_keys.items():
            record = flex.get(record_key)
            self.flex_hit_labels[key].configure(text=format_number(float(record.get("Value", 0))) if isinstance(record, dict) else "0")
        self.flex_lifetime_labels["damage"].configure(text=format_number(float(flex.get("LifetimeDamage", 0))))
        self.flex_lifetime_labels["healing"].configure(text=format_number(float(flex.get("LifetimeHealing", 0))))
        self.flex_lifetime_labels["runs"].configure(text=str(int(flex.get("RunsTracked", 0))))

        self.map_label.configure(text=self.current_map)
        folder = self.watcher.folder
        self.log_path_label.configure(text=f"Log folder: {folder}" if folder else "Log folder: auto-detect")

    def _update_overlay_opacity(self, in_run: bool) -> None:
        try:
            normal_opacity = min(1.0, max(0.2, float(self.settings.get("OverlayOpacity"))))
        except (TypeError, ValueError):
            normal_opacity = 1.0
        settings_open = bool(self.settings_view.winfo_ismapped())
        should_fade = bool(self.settings.get("FadeWhenAfk")) and not in_run and not settings_open
        lock_factor = 0.92 if self.locked else 1.0
        target = (0.08 if should_fade else normal_opacity) * lock_factor
        try:
            fade_seconds = min(60.0, max(1.0, float(self.settings.get("AfkFadeSeconds"))))
        except (TypeError, ValueError):
            fade_seconds = 6.0
        faded_target = 0.08 * lock_factor
        normal_target = normal_opacity * lock_factor
        fade_step = max(0.0001, abs(normal_target - faded_target) / (fade_seconds * 4.0))
        step = 0.12 if target > self.current_opacity else fade_step
        if abs(target - self.current_opacity) <= step:
            self.current_opacity = target
        else:
            self.current_opacity += step if target > self.current_opacity else -step
        self.root.attributes("-alpha", min(1.0, max(0.05, self.current_opacity)))

    def _redraw_bars(self) -> None:
        if not hasattr(self, "colors"):
            return
        for row in self.ability_rows:
            canvas: tk.Canvas = row["bar"]
            canvas.delete("all")
            width = max(1, canvas.winfo_width())
            canvas.create_rectangle(0, 0, width, 3, fill=self.colors["bar_bg"], outline="")
            left = 0.0
            segment_colors = {"normal": "#F4F7FB", "crit": self.colors["red"], "heavy": self.colors["orange"], "dev": self.colors["purple"]}
            for category in ("normal", "crit", "heavy", "dev"):
                segment_width = width * float(row.get("segments", {}).get(category, 0.0)) / 100.0
                if segment_width > 0:
                    canvas.create_rectangle(left, 0, min(width, left + segment_width), 3,
                                            fill=segment_colors[category], outline="")
                left += segment_width

    def _show_ability_tooltip(self, row: dict[str, Any], event: tk.Event) -> None:
        if row.get("ability") is None:
            return
        if self._ability_tooltip_hide_job is not None:
            self.root.after_cancel(self._ability_tooltip_hide_job)
            self._ability_tooltip_hide_job = None
        if self._ability_tooltip is not None and self._ability_tooltip_row is row:
            self._position_ability_tooltip(row)
            return
        self._hide_ability_tooltip()
        ability = row["ability"]
        tip = tk.Toplevel(self.root)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        outer = tk.Frame(tip, background="#171C27", highlightbackground="#3A4352", highlightthickness=1)
        outer.pack(fill="both", expand=True)
        tk.Label(outer, text=ability["name"], background="#171C27", foreground="#F4F7FB",
                 font=(self.FONT, self._scaled_font_size(9), "bold"), anchor="w").pack(fill="x", padx=10, pady=(8, 5))
        colors = {"normal": "#F4F7FB", "crit": self.colors["red"], "heavy": self.colors["orange"], "dev": self.colors["purple"]}
        titles = {"normal": "Normal", "crit": "Crit", "heavy": "Heavy", "dev": "Devastating"}
        for category in ("normal", "crit", "heavy", "dev"):
            stats = ability["breakdown"][category]
            line = tk.Frame(outer, background="#171C27")
            line.pack(fill="x", padx=10, pady=1)
            tk.Label(line, text=titles[category], width=11, background="#171C27", foreground=colors[category],
                     font=(self.FONT, self._scaled_font_size(8)), anchor="w").pack(side="left")
            hits = int(stats["hits"])
            hit_word = "hit" if hits == 1 else "hits"
            detail = f"{hits:,} {hit_word}   {format_number(float(stats['damage']))} · {stats['percent']:.1f}%   avg {format_number(float(stats['average']))}"
            tk.Label(line, text=detail, background="#171C27", foreground="#F4F7FB",
                     font=(self.FONT, self._scaled_font_size(8)), anchor="w").pack(side="left")
        if float(ability.get("non_damage", 0.0)) > 0:
            tk.Label(outer, text=f"Healing / shielding   {format_number(float(ability['non_damage']))}",
                     background="#171C27", foreground=self.colors["green"], font=(self.FONT, self._scaled_font_size(8)),
                     anchor="w").pack(fill="x", padx=10, pady=(5, 8))
        else:
            tk.Frame(outer, height=7, background="#171C27").pack()
        self._ability_tooltip = tip
        self._ability_tooltip_row = row
        tip.bind("<Enter>", self._cancel_hide_ability_tooltip, add="+")
        tip.bind("<Leave>", self._schedule_hide_ability_tooltip, add="+")
        self._position_ability_tooltip(row)

    def _position_ability_tooltip(self, row: dict[str, Any]) -> None:
        if self._ability_tooltip is None:
            return
        self._ability_tooltip.update_idletasks()
        row_widget: tk.Widget = row["frame"]
        row_x = row_widget.winfo_rootx()
        row_y = row_widget.winfo_rooty()
        row_width = row_widget.winfo_width()
        tip_width = self._ability_tooltip.winfo_width()
        x = row_x + row_width + 2
        if x + tip_width > self.root.winfo_screenwidth() - 8:
            x = row_x - tip_width - 2
        y = row_y
        y = min(y, self.root.winfo_screenheight() - self._ability_tooltip.winfo_height() - 8)
        self._ability_tooltip.geometry(f"+{max(0, x)}+{max(0, y)}")

    def _cancel_hide_ability_tooltip(self, _event: tk.Event | None = None) -> None:
        if self._ability_tooltip_hide_job is not None:
            self.root.after_cancel(self._ability_tooltip_hide_job)
            self._ability_tooltip_hide_job = None

    def _schedule_hide_ability_tooltip(self, _event: tk.Event) -> None:
        if self._ability_tooltip_hide_job is not None:
            self.root.after_cancel(self._ability_tooltip_hide_job)
        self._ability_tooltip_hide_job = self.root.after(250, self._hide_ability_tooltip)

    def _hide_ability_tooltip(self) -> None:
        if self._ability_tooltip_hide_job is not None:
            try:
                self.root.after_cancel(self._ability_tooltip_hide_job)
            except tk.TclError:
                pass
            self._ability_tooltip_hide_job = None
        if self._ability_tooltip is not None:
            self._ability_tooltip.destroy()
        self._ability_tooltip = None
        self._ability_tooltip_row = None

    def find_and_follow(self, force: bool = False) -> None:
        found = self.win.find_soulbound() if hasattr(self, "win") else None
        if found is None:
            self.game_window = self.game_pid = None
            self.process_connected = False
            self.process_status = "Soulbound is not running"
            return
        self.game_window, self.game_pid = found
        self.process_connected = True
        self.process_status = f"Attached · PID {self.game_pid}"
        if not self.follow_var.get():
            return
        rect = self.win.window_rect(self.game_window)
        if rect is None:
            return
        target_left = rect[2] - self.root.winfo_width() - 22
        target_top = rect[1] + 54
        if force or abs(self.root.winfo_x() - target_left) > 1 or abs(self.root.winfo_y() - target_top) > 1:
            self.root.geometry(f"+{target_left}+{target_top}")

    def toggle_lock(self) -> None:
        self.locked = not self.locked
        self.win.set_click_through(self.locked)
        self.refresh()

    def start_drag(self, event: tk.Event) -> None:
        if self.locked:
            return
        if self.follow_var.get():
            self.follow_var.set(False)
            self.follow_changed()
        self._drag_start = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())

    def drag_window(self, event: tk.Event) -> None:
        if not self._drag_start or self.locked:
            return
        start_x, start_y, left, top = self._drag_start
        self.root.geometry(f"+{left + event.x_root - start_x}+{top + event.y_root - start_y}")

    def start_resize(self, event: tk.Event) -> None:
        if not self.locked:
            self._resize_start = (event.x_root, event.y_root, self.root.winfo_width(), self.root.winfo_height())

    def resize_window(self, event: tk.Event) -> None:
        if not self._resize_start or self.locked:
            return
        start_x, start_y, width, height = self._resize_start
        new_width = max(320, width + event.x_root - start_x)
        new_height = max(560, height + event.y_root - start_y)
        self.root.geometry(f"{new_width}x{new_height}")

    def _store_window_size(self) -> None:
        if self.root.state() != "iconic":
            min_width, min_height = self._active_min_size()
            width = max(min_width, self.root.winfo_width())
            height = max(min_height, self.root.winfo_height())
            width_key, height_key = self._mode_size_keys(self.compact_mode)
            self.settings.data[width_key] = width
            self.settings.data[height_key] = height
            if not self.compact_mode:
                self.settings.data["WindowWidth"] = width
                self.settings.data["WindowHeight"] = height

    def finish_resize(self, _event: tk.Event | None = None) -> None:
        self._resize_start = None
        self._store_window_size()
        self.settings.save()

    def minimize(self) -> None:
        if self.closed or self._minimized:
            return
        self._hide_ability_tooltip()
        self._minimized = True
        # A borderless Tk window cannot be safely iconified directly. Temporarily
        # give it standard Windows chrome so it has a real taskbar entry and can
        # be restored, then put the custom overlay chrome back after it maps.
        self.root.attributes("-topmost", False)
        self.root.overrideredirect(False)
        self.root.update_idletasks()
        self.root.iconify()
        self._restore_binding = self.root.bind("<Map>", self._restore_from_minimize, add="+")

    def _restore_from_minimize(self, _event: tk.Event | None = None) -> None:
        if self._minimized:
            self.root.after_idle(self._finish_restore)

    def _finish_restore(self) -> None:
        if not self._minimized or self.root.state() == "iconic":
            return
        if self._restore_binding:
            self.root.unbind("<Map>", self._restore_binding)
            self._restore_binding = None
        self._minimized = False
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.lift()

    def tick(self) -> None:
        if self.closed:
            return
        try:
            self.watcher.poll()
            now = time.monotonic()
            if now - self.last_process_poll >= 0.75:
                self.find_and_follow()
                self.last_process_poll = now
            if self.win.poll_hotkey():
                self.toggle_lock()
            self.refresh()
        except Exception as error:
            self.log_connected = False
            self.log_status = f"Meter error: {type(error).__name__}"
        self.root.after(250, self.tick)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self._brand_animation_job is not None:
            try:
                self.root.after_cancel(self._brand_animation_job)
            except tk.TclError:
                pass
            self._brand_animation_job = None
        self.settings.data["FollowGameWindow"] = bool(self.follow_var.get())
        self.settings.data["CompactMode"] = self.compact_mode
        self.settings.data["WindowLeft"] = self.root.winfo_x()
        self.settings.data["WindowTop"] = self.root.winfo_y()
        self._store_window_size()
        self.settings.save()
        self.records.save(force=True)
        if hasattr(self, "win"):
            self.win.close()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def replay_log(path: Path, include_overkill: bool = False) -> dict[str, Any]:
    session = CombatSession()
    resolver = CombatAbilityResolver()
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            try:
                root = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(root, dict):
                continue
            resolver.observe(root)
            event = parse_combat_event(root)
            if event:
                session.apply(live_damage_event(resolver.resolve(event), include_overkill))
    return session.snapshot()


def run_self_test(log_path: str | None = None) -> int:
    assert map_name_from_log_path(
        r"C:\logs\dungeon__Virelda_Outskirts__1__2026-08-20_17-03-17Z.log"
    ) == "Virelda Outskirts"
    event = parse_combat_event({
        "timestamp_utc": timestamp_text(utc_now()), "event": "DAMAGE_DEALT", "sequence": 1,
        "data": {"source": {"type": "self"}, "ability_display_name": "Bomb",
                 "impact_type": "void", "post_target_mitigation_amount": 300, "applied_amount": 1,
                 "is_crit": True, "is_heavy_hit": True},
    })
    assert event and event.amount == 300 and event.applied_amount == 1
    assert live_damage_event(event, False).amount == 1 and live_damage_event(event, True).amount == 300
    session = CombatSession()
    session.apply(live_damage_event(event, False))
    unknown = replace(event, event_id="unknown", sequence=2, ability_name="Unknown Ability", amount=209,
                      applied_amount=209, critical=False, heavy_hit=False)
    session.apply(live_damage_event(unknown, False))
    snap = session.snapshot()
    assert snap["damage"] == 210 and snap["abilities"][0]["name"] == "Bomb"
    assert snap["abilities"][0]["damage_type"] == "VOID"
    assert snap["dev_rate"] == 50 and snap["highest_dev"] == 1
    assert snap["abilities"][0]["breakdown"]["dev"]["hits"] == 1
    assert snap["abilities"][0]["segments"]["dev"] == 100
    assert snap["in_run"]
    ended = parse_combat_event({
        "timestamp_utc": timestamp_text(utc_now()), "event": "RUN_END", "sequence": 3,
    })
    assert ended
    session.apply(ended)
    assert not session.snapshot()["in_run"]

    rewrite_events = [
        parse_combat_event({"timestamp_utc": timestamp_text(utc_now()), "event": "RUN_START", "sequence": 10}),
        parse_combat_event({"timestamp_utc": timestamp_text(utc_now()), "event": "ENCOUNTER_START", "sequence": 11}),
        parse_combat_event({
            "timestamp_utc": timestamp_text(utc_now()), "event": "DAMAGE_DEALT", "sequence": 12,
            "data": {"source": {"type": "self"}, "ability_display_name": "Bomb", "applied_amount": 123},
        }),
    ]
    assert all(rewrite_events)
    rewrite_session = CombatSession()
    for rewrite_event in rewrite_events:
        assert rewrite_event
        rewrite_session.apply(rewrite_event)
    assert rewrite_session.snapshot()["damage"] == 123
    assert rewrite_events[0]
    rewrite_session.apply(rewrite_events[0])
    assert rewrite_session.snapshot()["damage"] == 123
    for rewrite_event in rewrite_events[1:]:
        assert rewrite_event
        rewrite_session.apply(rewrite_event)
    rewrite_snapshot = rewrite_session.snapshot()
    assert rewrite_snapshot["damage"] == 123 and rewrite_session.damage_hit_count == 1 and rewrite_snapshot["in_run"]

    resolver = CombatAbilityResolver()
    resolver.observe({"event": "LOADOUT_SNAPSHOT", "data": {"abilities": [{"ability_display_name": "Fortify"}, {"ability_display_name": "Healing Pulse"}]}})
    shield = parse_combat_event({"timestamp_utc": timestamp_text(utc_now()), "event": "SHIELD_GAINED", "data": {"source": {"type": "self"}, "ability_display_name": "Unknown Ability", "amount": 100}})
    heal = parse_combat_event({"timestamp_utc": timestamp_text(utc_now()), "event": "HEAL_DEALT", "data": {"source": {"type": "self"}, "ability_display_name": "Unknown Ability", "effective_amount": 50}})
    assert shield and resolver.resolve(shield).ability_name == "Fortify"
    assert heal and resolver.resolve(heal).ability_name == "Healing Pulse"

    with tempfile.TemporaryDirectory(prefix="DpsMeterPythonTest-") as folder:
        store = FlexRecordStore(Path(folder) / "records.txt")
        store.begin_log(str(Path(folder) / "run.log"))
        store.apply(event)
        store.save(force=True)
        loaded = json.loads((Path(folder) / "records.txt").read_text(encoding="utf-8"))
        assert loaded["LifetimeDamage"] == 300 and loaded["RunsTracked"] == 1

    with tempfile.TemporaryDirectory(prefix="DpsMeterLogPinTest-") as folder:
        test_folder = Path(folder)
        old_log = test_folder / "dungeon__Test__1__2026-08-30_21-00-00Z.log"
        active_log = test_folder / "dungeon__Test__1__2026-08-30_22-00-00Z.log"
        header = '{"event":"LOG_HEADER","data":{"format":"soulbound_combat_log"},"sequence":1}\n'
        run_start = '{"timestamp_utc":"2026-08-30T22:00:00Z","event":"RUN_START","sequence":2}\n'
        first_hit = '{"timestamp_utc":"2026-08-30T22:00:01Z","event":"DAMAGE_DEALT","data":{"source":{"type":"self"},"ability_display_name":"Bomb","applied_amount":20},"sequence":3}\n'
        next_hit = '{"timestamp_utc":"2026-08-30T22:00:02Z","event":"DAMAGE_DEALT","data":{"source":{"type":"self"},"ability_display_name":"Bomb","applied_amount":10},"sequence":4}\n'
        old_log.write_text(header + run_start, encoding="utf-8")
        active_log.write_text(header + run_start + first_hit, encoding="utf-8")
        watcher_session = CombatSession()
        selected_logs: list[str] = []
        watcher = CombatLogWatcher(str(test_folder), False, watcher_session.apply, selected_logs.append,
                                   lambda _connected, _message: None)
        watcher.poll()
        first_watch_snapshot = watcher_session.snapshot()
        assert first_watch_snapshot["damage"] == 20 and len(selected_logs) == 1 and Path(selected_logs[0]) == active_log.resolve(), (
            first_watch_snapshot["damage"], selected_logs, watcher.active_path)
        active_log.write_text("", encoding="utf-8")
        watcher.poll()
        assert watcher.active_path == active_log.resolve() and len(selected_logs) == 1
        assert watcher_session.snapshot()["damage"] == 20
        active_log.write_text(header + run_start + first_hit + next_hit, encoding="utf-8")
        watcher.poll()
        assert watcher_session.snapshot()["damage"] == 30 and len(selected_logs) == 1

    print(f"PASS Python DPS Meter {VERSION}")
    if log_path:
        real = replay_log(Path(log_path))
        print(f"REAL damage={real['damage']:.3f} healing={real['healing']:.3f} shield={real['shielding']:.3f}")
        for ability in real["abilities"]:
            print(f"ABILITY {ability['name']} [{ability['damage_type']}]={ability['amount']:.3f}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Soulbound DPS Meter Python edition")
    parser.add_argument("--log", help="Combat-log file or folder to use")
    parser.add_argument("--self-test", action="store_true", help="Run parser and persistence tests without opening the UI")
    parser.add_argument("--smoke-ui", type=float, metavar="SECONDS", help=argparse.SUPPRESS)
    parser.add_argument("--version", action="version", version=VERSION)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test(args.log)
    app = MeterApp(args.log, args.smoke_ui)
    app.run()
    return 0



# Embedded branding keeps the readable Python release completely self-contained.
# Generated from the project artwork; edit the source images rather than these bytes.
APP_ICON_PNG_BASE64 = (
    "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"
    "DSB3Dlnwf44POsj5APn4L8lcdHihlNTCC5DY4QBSCtw7e67uIklSQQ9OciM33SAxaCxve2i2MII7IKN83GSgjNT+sti3AV2DUDGc"
    "uHiGWcrUjEFDJQghKgWEYcDe0hZOPPo8j3zuDwgaZViI0dXELf6Wt0kvEnyyAcdkHYhqG7VhFdt06d8kDILxhBLTh32YIf5Et3oY"
    "mILkRJdu6T8Ya96XgCY9hWgxHUlAI5iYrrI9mmONuMAl8S1kkXzkA8NKJmIrNVbiOqQpYqV/h8m3tsGPqtDCKAPcDt1s8euwlVx3"
    "V5Tr9APzt5tmXABLYOG0x+VKoTPaiZPR0fH5JluodHL0Xzauljdcy+M2gIXCfcy68qVgq9MVKBTRZs2JIfmHHrg0Xgk90QHgXN2N"
    "DWPgwJz7eb2BTcDPSIcQ07E9RNHVYhwRqB80EhlF/Jf+UZgW5tydDFLhwsI1JuKQ7dEkWZAhoQt5jULDVqaY0DLGRrDmYrFpOw0/"
    "sXWutd54RDMdtuTSPmZ0oYLtVTg6+EnllYqFiKCwTqUbWVB8/P4hifRfj31qyOF9M/ft15yUA/3eiLioc5d6rMxOTjIzMcWK9XK+"
    "rvOvf9wAx00wjqU4aSrsYoalxqrbJOnXcMiQTzf9i1RGePQNMkNHZk4wRqKep/lucsFahXKI7JtyVV6WwoWG+7dayT3rJPWHa//z"
    "FyP9IbkiiO//N1kyG67lcRvAvP+B+U11zknqdi1/QdiOK2eKm0S3VbKe0TVddSfFSgyXG+70nCnB9gkHasn4sZ6M22lVN0ILCq2D"
    "bGwlOnAS9NShg+KOQinW/SfxbsKwsLhEfbXBgWAbgZcMuwPWUiGgHARY+sd6fQq2rKfq643RpN+CTHUY3MwNIoriqYK7EaklxLhD"
    "WBUjOgSwFt9PHQDR1T+edJmbRbZgf2hHfur3hZ4an2EQeWuzKuzdvp00SHhNl3s5ETmxCet+JvKy8nLAFspUCTm5cg7aXoDkswZG"
    "0sN1YLyrGyh5Rop4tND26QiKai/GbuxqzHGQQzWnFM2Ay00//jPI3IQLCMl0ONxG1bVEuXGK5KYr10UBnhdYkDFreaMWYN7fVzbd"
    "1bwYqLh7itU+mK17cLZimJ1ESpH7/lNr3dZIjs8Mv7nKWGbgyE2p78e136hxkCM/SC4SRjgOFUaIqkOkka76qzCjMamgC02uLCyw"
    "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"
    "twAAAABJRU5ErkJggg=="
)
BRAND_ANIMATION_SHEET_BASE64 = (
    "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"
    "rEAS7vV56E++RPLHO7ne2cB9+kk616zFSTrIokT4GlVXc9rf+J22NLaQiIo5cqX8YMbfqAX9hA5Cs+0SKrSnEM2J+PxjfJhYET8I"
    "FDrQiDCibV0fN/2f11HpbWVzMcH2j/8DX/ujf0MOmYLoqRcuoeudl5uShlohAoXwHZ74x5/QP2mW9/JJTfOCNlQQmAZTGtHYP42X"
    "ymWLiw7MbEgobe6whSfmbGOcsp9QQaAQYUTr2l62/OXLGJwnuHqqiaGP/iff+JMvIobNgerkbYvp/P3L4sP/2tQYPZE/apRqU0dU"
    "Vj5f/ra1vVz65y9nZ1+FdSM21Q/cy0///JuIcY2U0PmCtSx48/VmNVPFfs/h8X/8Cf1Tp+NPnNzvm3JmOlRQn+NvHIVW5niHiR+F"
    "DiNa1/Zx6Z+9nB19ZZYdjqi8816e+OsfYVdsLAeWvehKNrz5JWZ/OzLfWXguj//fOe2f0jQvaDdB3ShLqfWRe0QtCdMB44pHnCv/"
    "ul4u/bOXs7OvzLLBkOrbv8uOv/kRTt3BSkrWveRGrvr9X0KkTaKHCCJE2TH+qTPzC80x25+GP1DmQdbsHtsfGT9RRNu6Xi7/+CvZ"
    "2Vdl2VBA+e3fYscnf4BVsxAJWPvS53HtO1+LyMTnTeshYszi4b/9Hv0TErSkkNE093egAn9O/MwUHYr7b8Icl2vce3xWfvPv6Nh/"
    "6Z+9gl29VZYOepTf1vDbIGDhnVdwyXtehkxZqFCj6yFyAO79y6/QPFCBUFDIQVN/+wn9oiWJqkcoT8X9M3imPwhn6ndTj2biByFm"
    "/XH/NX5F2/p5XP6xV7Kzq8qyYZ/yu77Bk5/4H2TJLJ223rGWxe++CStlm+9dC5EH4J5Pfh49NkSlUmKyWdG8oOPI/jtztWvc/u1J"
    "/OkaQSkgqvqoinfGfj3Xv+E4/rKF0NByx2q633m1uTs7Mg9XeQju+Yd/RxSHGWSUA7lpWnrbUaFvVhyO4U8uaMafqhEUPaJaQJCv"
    "nrl/Jn5O0P6xv/WOtfTM8VOPkKM23/vcf9JULTMl8uxJTdDU1ooK4731+BrEuf7MsnakEua8uRSNCdATcy9juN8M7KE5dlINkW3J"
    "2ftJ40sTxJwrl7RlUapXUFXNRdUc93zoL3ng0z/AnhJEfojSEqtmyvrhWuYAfiOppxwQFKoIx0FpFW+GxwGq9ExlpkYxCNGWRpdi"
    "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"
    "N/7ajgmCvI9t2WjqfvMMz/rbk2ZLezLy59Lo0pn7Y61pep67HhUoaoenaF7bRej5TH57J/54+aT+NW+/mdol3bjtsaP9dt2vzfMr"
    "I//EOfRH8WM3JWi7ehmh0tQOT8/6D3/mPqqHZhC2NWs4nr8a+VuP9dcLdTSO/3nwy7hDfHkPKlSEEwUSC7NopZj81k5qg3mELRFS"
    "mrdGO/InLOIrcqx5+43GH8V/7eEJgrw352+Mn4ofxX8CkbTRUzV0Koadi+Jfnd38Eyptnt9u8/y6DwwTTlfNojP6MJ0d/8i/+gny"
    "ixNki20VUiyxFrSjAFWsYfelTOr4rsnZFQwCsCVWzCGMW4j+JAtetJ7YyzdS7GknoTXz6GGBWElqaoiHPvUFHvr0zwlGqqjAI3B9"
    "U2BcR/VOtcJa3oZIOIRDFUQmjiUlwYFxdKgeBS44heyy4/t7U2jvVPwXkHj5RsZ70pSYpIM2VrKBBRMej/z3N7j/Mz/EO1JBBQGB"
    "60X+qFbrufb3t6MEqILx4wUEu4/xW3W/RPYlmPfCC4j/wQVM9jaRZwyJpJ+lrBlOMvWFn7Llf36Ce7CM9n0Cb278hdJorbCWtUHS"
    "IRwsI5sSWEISHHwi/euJv2oDU33NFNUogQzJ0MmygxI++xA7v34X3uHH+mfjZ2mbSdA5W78llyRW9hJqRThZwe5Loyou/s6Jk/rn"
    "v3A9sVdtYLKviXw4jNaKpN1B774q1ke3ceg72/BGquD7BL5vtt3PtV+IrdKRS9quXUEoNLXDeZKLs3iTJYq/PGQ++KU05ZVsieXE"
    "COMC2ZVg3gvWEvuj9Uz0Zyh442ilSCU66N1bIfx/Wxn8zg7UpIsOA+M/dvyXtCKSc/FvSwv/4Dhand74y7i9pOdZ6yEmqR6eJrex"
    "h9pIgaGvPGimLdtcZzmu/4/XMzk/Q74yAkqTynTSs7dG8P+2MPStHai8iw7Oo1+Y+MleuAiSNsFEieymHsJCjZGvbQNEdJ3xZP40"
    "+fIoOtSkmjvpjfzD39qJKtRQQUjgeedt/IUUS5xFXShLoAtVEotz4IeU7z5s4seKrkPZAisWI3QEsiNB3/NXE/uTtUwuaCKfH0Mr"
    "RbqlnZ5HXML3P8jIbbsIizVUGBz/+V3cikg4BCMVZCaOJST+oXFQ+vT8Qiyx+9sJhUblazh9GfB9/N2TDfF/Jv6d5i5z0OhvmP9P"
    "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"
    "YII="
)

if __name__ == "__main__":
    raise SystemExit(main())
