"""Validated server.properties options exposed by the ServerMaker panel."""

from __future__ import annotations

import re
from pathlib import Path

def _bool(key: str, label: str, group: str, default: bool, note: str = "") -> dict:
    return {"key": key, "label": label, "group": group, "kind": "bool", "default": str(default).lower(), "note": note}


def _int(key: str, label: str, group: str, default: int, low: int, high: int) -> dict:
    return {"key": key, "label": label, "group": group, "kind": "int", "default": str(default), "min": low, "max": high, "note": ""}


def _enum(key: str, label: str, group: str, default: str, choices: tuple[str, ...]) -> dict:
    return {"key": key, "label": label, "group": group, "kind": "enum", "default": default, "choices": list(choices), "note": ""}


def _text(key: str, label: str, group: str, default: str) -> dict:
    return {"key": key, "label": label, "group": group, "kind": "text", "default": default, "note": ""}


PROPERTIES = [
    _text("motd", "Message of the day", "Gameplay", "DensitySMP"),
    _int("max-players", "Maximum players", "Gameplay", 20, 1, 1000),
    _enum("difficulty", "Difficulty", "Gameplay", "normal", ("peaceful", "easy", "normal", "hard")),
    _enum("gamemode", "Default game mode", "Gameplay", "survival", ("survival", "creative", "adventure", "spectator")),
    _bool("force-gamemode", "Force default game mode on join", "Gameplay", False),
    _bool("pvp", "Player vs player combat", "Gameplay", True),
    _bool("hardcore", "Hardcore mode", "Gameplay", False, "Players are banned on death."),
    _bool("allow-flight", "Allow flight", "Gameplay", False, "Needed for flying mods; can trigger anti-cheat."),
    _bool("allow-nether", "Allow the Nether", "Gameplay", True),
    _bool("allow-end", "Allow The End", "Gameplay", True),
    _int("spawn-protection", "Spawn protection radius", "Gameplay", 16, 0, 1000),
    _int("player-idle-timeout", "Idle kick timeout (minutes, 0 = never)", "Gameplay", 0, 0, 10000),
    _int("max-world-size", "Maximum world radius (blocks)", "Gameplay", 29999984, 1, 29999984),
    _bool("enable-command-block", "Enable command blocks", "Gameplay", False),
    _int("op-permission-level", "Operator permission level", "Gameplay", 4, 1, 4),
    _int("function-permission-level", "Function permission level", "Gameplay", 2, 1, 4),
    _bool("white-list", "Whitelist enabled", "Access and safety", False),
    _bool("enforce-whitelist", "Kick non-whitelisted players now", "Access and safety", False),
    _bool("online-mode", "Verify accounts with Mojang", "Access and safety", True, "Turn off only behind a trusted proxy."),
    _bool("enforce-secure-profile", "Require secure chat profiles", "Access and safety", True),
    _bool("prevent-proxy-connections", "Block proxy connections", "Access and safety", False),
    _bool("hide-online-players", "Hide player list from status", "Access and safety", False),
    _bool("enable-status", "Show in server list", "Access and safety", True),
    _bool("broadcast-console-to-ops", "Show console output to operators", "Access and safety", True),
    _bool("accepts-transfers", "Accept player transfers", "Access and safety", False),
    _int("rate-limit", "Packet rate limit (0 = off)", "Access and safety", 0, 0, 1000),
    _int("pause-when-empty-seconds", "Pause world after empty seconds", "Performance", 60, -1, 3600),
    _int("view-distance", "View distance (chunks)", "Performance", 8, 3, 32),
    _int("simulation-distance", "Simulation distance (chunks)", "Performance", 6, 3, 32),
    _int("entity-broadcast-range-percentage", "Entity visibility (%)", "Performance", 100, 10, 1000),
    _int("max-tick-time", "Watchdog tick limit (ms)", "Performance", 60000, 1000, 600000),
    _int("network-compression-threshold", "Network compression threshold", "Performance", 256, -1, 65536),
    _int("max-chained-neighbor-updates", "Max chained neighbor updates", "Performance", 1000000, 1, 10000000),
    _bool("sync-chunk-writes", "Synchronous chunk writes", "Performance", True),
    _bool("use-native-transport", "Native network transport", "Performance", True),
    _bool("spawn-animals", "Spawn animals", "Mobs and world", True),
    _bool("spawn-monsters", "Spawn monsters", "Mobs and world", True),
    _bool("spawn-npcs", "Spawn villagers", "Mobs and world", True),
    _bool("generate-structures", "Generate structures", "Mobs and world", True),
    _bool("enable-jmx-monitoring", "Expose JMX monitoring", "Advanced", False),
]

PROPERTY_BY_KEY = {prop["key"]: prop for prop in PROPERTIES}


def validate_property(key: str, raw: object) -> str:
    prop = PROPERTY_BY_KEY.get(key)
    if prop is None:
        raise ValueError(f"Unknown server setting: {key}.")
    value = str(raw).strip()
    if "\n" in value or "\r" in value or len(value) > 256:
        raise ValueError(f"{prop['label']} must be a single line of at most 256 characters.")
    kind = prop["kind"]
    if kind == "bool":
        if value.lower() not in ("true", "false"):
            raise ValueError(f"{prop['label']} must be on or off.")
        return value.lower()
    if kind == "int":
        if not re.fullmatch(r"-?\d+", value):
            raise ValueError(f"{prop['label']} must be a whole number.")
        number = int(value)
        if not prop["min"] <= number <= prop["max"]:
            raise ValueError(f"{prop['label']} must be between {prop['min']} and {prop['max']}.")
        return str(number)
    if kind == "enum":
        if value not in prop["choices"]:
            raise ValueError(f"{prop['label']} must be one of: {', '.join(prop['choices'])}.")
        return value
    return value


def read_properties(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key] = value
    return values


def set_property_text(text: str, key: str, value: str) -> str:
    lines = text.splitlines()
    prefix = f"{key}="
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            lines[index] = prefix + value
            break
    else:
        lines.append(prefix + value)
    return "\n".join(lines) + "\n"
