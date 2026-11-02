#!/usr/bin/env python3
"""ServerMaker panel and Paper server supervisor."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import shlex
import signal
import socket
import struct
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import activity
from properties import PROPERTIES, read_properties, validate_property, write_property

try:
    import psutil
except ImportError as exc:
    raise SystemExit("Missing dependency: install requirements.txt with python3 -m pip install -r requirements.txt") from exc


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SERVER = DATA / "servers" / "DensitySMP"
BACKUPS = DATA / "backups"
LOGS = DATA / "logs"
SETTINGS_FILE = DATA / "settings.json"
PID_FILE = DATA / "panel.pid"
LOCK_FILE = DATA / "panel.lock"
PAPER_JAR = SERVER / "paper.jar"
CONSOLE_LOG = LOGS / "console.log"
PANEL_HOST = os.environ.get("SERVERMAKER_HOST", "0.0.0.0")
PANEL_PORT = int(os.environ.get("SERVERMAKER_PORT", "8080"))
MINECRAFT_PORT = 25565
PAPER_VERSION = "1.21.11"
PAPER_BUILD = 132
PAPER_SHA256 = "5ffef465eeeb5f2a3c23a24419d97c51afd7dbb4923ff42df9a3f58bba1ccfba"
SAFE_MEMORY_RESERVE_MB = 2048
MAX_UPLOAD_BYTES = 128 * 1024 * 1024
JVM_FORBIDDEN_PREFIXES = ("-Xms", "-Xmx", "-jar", "-cp", "-classpath", "--class-path", "-javaagent", "-agentpath")
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
}
PLAYER_ACTIONS = {
    "kick": "kick {name}",
    "op": "op {name}",
    "deop": "deop {name}",
    "whitelist-add": "whitelist add {name}",
    "whitelist-remove": "whitelist remove {name}",
}


def safe_memory_mb() -> int:
    available = int(psutil.virtual_memory().available / (1024 * 1024))
    try:
        limit = int(Path("/sys/fs/cgroup/memory.max").read_text().strip())
        current = int(Path("/sys/fs/cgroup/memory.current").read_text().strip())
        if limit > 0:
            available = min(available, max(0, (limit - current) // (1024 * 1024)))
    except (OSError, ValueError):
        pass
    manager = globals().get("MANAGER")
    process = getattr(manager, "process", None)
    if process is not None and process.poll() is None:
        try:
            available += int(psutil.Process(process.pid).memory_info().rss / (1024 * 1024))
        except (psutil.Error, OSError):
            pass
    return max(1024, min(8192, ((available - SAFE_MEMORY_RESERVE_MB) // 1024) * 1024))


def parse_jvm_args(text: str) -> list[str]:
    if "\n" in text or "\r" in text or len(text) > 1000:
        raise ValueError("JVM arguments must be a single line of at most 1000 characters.")
    try:
        tokens = shlex.split(text)
    except ValueError as exc:
        raise ValueError("JVM arguments have an unmatched quote.") from exc
    for token in tokens:
        if not re.fullmatch(r"-[A-Za-z0-9_.:=,+/-]+", token) or token.startswith(JVM_FORBIDDEN_PREFIXES):
            raise ValueError(f"JVM argument not allowed: {token}")
        if re.search(r"-XX:[+-]?Use\w*GC\b", token):
            raise ValueError("The garbage collector is already chosen by the panel; remove it from the start options.")
    return tokens


def ensure_layout() -> None:
    for path in (SERVER, BACKUPS, LOGS, SERVER / "plugins"):
        path.mkdir(parents=True, exist_ok=True)
    if not SETTINGS_FILE.exists():
        SETTINGS_FILE.write_text(json.dumps({
            "auto_start": True,
            "memory_mb": safe_memory_mb(),
            "restart_delay_seconds": 10,
            "jvm_args": "",
            "server_name": "DensitySMP",
            "software": "Paper",
            "minecraft_version": PAPER_VERSION,
            "paper_build": PAPER_BUILD,
            "server_port": MINECRAFT_PORT,
            "eula": True,
        }, indent=2) + "\n")
    if not (SERVER / "eula.txt").exists():
        (SERVER / "eula.txt").write_text("# Accepted by the server owner.\neula=true\n")
    if not (SERVER / "server.properties").exists():
        (SERVER / "server.properties").write_text(
            "# ServerMaker-managed DensitySMP settings\n"
            "enable-jmx-monitoring=false\n"
            "enable-rcon=false\n"
            "level-seed=\n"
            "gamemode=survival\n"
            "enable-command-block=false\n"
            "enable-query=false\n"
            "generator-settings={}\n"
            "enforce-secure-profile=true\n"
            "level-name=world\n"
            "motd=DensitySMP\n"
            "query.port=25565\n"
            "pvp=true\n"
            "difficulty=normal\n"
            "network-compression-threshold=256\n"
            "max-tick-time=60000\n"
            "max-players=20\n"
            "online-mode=true\n"
            "server-port=25565\n"
            "server-ip=\n"
            "spawn-protection=16\n"
            "view-distance=8\n"
            "simulation-distance=6\n"
            "allow-flight=false\n"
            "level-type=minecraft:normal\n"
            "allow-nether=true\n"
            "sync-chunk-writes=true\n"
            "prevent-proxy-connections=false\n"
            "use-native-transport=true\n"
            "enable-status=true\n"
            "hide-online-players=false\n"
            "entity-broadcast-range-percentage=100\n"
            "player-idle-timeout=0\n"
            "force-gamemode=false\n"
            "rate-limit=0\n"
            "hardcore=false\n"
            "white-list=false\n"
            "broadcast-console-to-ops=true\n"
            "broadcast-rcon-to-ops=true\n"
            "spawn-npcs=true\n"
            "spawn-animals=true\n"
            "spawn-monsters=true\n"
        )


def load_settings() -> dict:
    return json.loads(SETTINGS_FILE.read_text())


def save_settings(settings: dict) -> None:
    temporary = SETTINGS_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(settings, indent=2) + "\n")
    temporary.replace(SETTINGS_FILE)


class Console:
    def __init__(self) -> None:
        self.lines: deque[dict] = deque(maxlen=1500)
        self.next_id = 0
        self.lock = threading.Lock()

    def add(self, text: str) -> None:
        with self.lock:
            self.next_id += 1
            self.lines.append({"id": self.next_id, "text": text.rstrip("\r\n")})

    def since(self, after: int = 0) -> list[dict]:
        with self.lock:
            return [line for line in self.lines if line["id"] > after]


class ServerManager:
    def __init__(self) -> None:
        self.console = Console()
        self.lock = threading.RLock()
        self.process: subprocess.Popen | None = None
        self.manual_stop = False
        self.last_exit: int | None = None
        self.last_start: str | None = None
        self.next_restart: float | None = None
        self.restart_count = 0
        self.thread = threading.Thread(target=self._supervise, daemon=True, name="server-supervisor")
        self.thread.start()

    def start(self) -> str:
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                return "Server is already running."
            if not PAPER_JAR.is_file():
                raise RuntimeError(f"Paper jar is missing: {PAPER_JAR}")
            self.manual_stop = False
            self.next_restart = None
            self._spawn()
            return "DensitySMP is starting."

    def _spawn(self) -> None:
        settings = load_settings()
        memory = max(1024, int(settings["memory_mb"]))
        java_home = os.environ.get("JAVA_HOME", "/usr/local/sdkman/candidates/java/21.0.13.0+2-ms")
        java = Path(java_home) / "bin" / "java"
        if not java.is_file():
            raise RuntimeError(f"Java executable not found: {java}")
        if PAPER_JAR.stat().st_size < 1_000_000:
            raise RuntimeError("Paper jar is incomplete; refusing to start.")
        if hashlib.sha256(PAPER_JAR.read_bytes()).hexdigest() != PAPER_SHA256:
            raise RuntimeError("Paper jar checksum does not match the official Paper build.")
        extra = parse_jvm_args(str(settings.get("jvm_args", "")))
        self.console.add(f"Starting Paper {PAPER_VERSION} build {PAPER_BUILD} with Java 21; heap {memory} MiB.")
        output = CONSOLE_LOG.open("a", encoding="utf-8", buffering=1)
        try:
            self.process = subprocess.Popen(
                [str(java), f"-Xms{memory}M", f"-Xmx{memory}M", "-XX:+UseG1GC",
                 "-XX:+ParallelRefProcEnabled", "-XX:MaxGCPauseMillis=200",
                 *extra, "-jar", str(PAPER_JAR), "--nogui"],
                cwd=SERVER, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1,
                start_new_session=True,
            )
        except Exception:
            output.close()
            self.process = None
            raise
        self.last_start = datetime.now(timezone.utc).isoformat()
        threading.Thread(target=self._read_output, args=(self.process, output), daemon=True).start()

    def _read_output(self, process: subprocess.Popen, output) -> None:
        try:
            assert process.stdout is not None
            for line in process.stdout:
                self.console.add(line)
                output.write(line)
        finally:
            output.close()

    def stop(self) -> str:
        with self.lock:
            self.manual_stop = True
            self.next_restart = None
            process = self.process
            if process is None or process.poll() is not None:
                return "Server is not running."
            self.console.add("Sending graceful stop command; world data will be preserved.")
            if process.stdin:
                try:
                    process.stdin.write("save-all flush\nstop\n")
                    process.stdin.flush()
                except (BrokenPipeError, OSError):
                    process.send_signal(signal.SIGTERM)
        try:
            process.wait(timeout=90)
        except subprocess.TimeoutExpired:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        with self.lock:
            self.last_exit = process.returncode
            self.process = None
        return "DensitySMP stopped gracefully."

    def restart(self) -> str:
        self.stop()
        return self.start()

    def command(self, text: str) -> None:
        if not text.strip() or "\n" in text or "\r" in text or "\x00" in text:
            raise ValueError("Enter one non-empty console command.")
        with self.lock:
            process = self.process
            if process is None or process.poll() is not None or process.stdin is None:
                raise RuntimeError("The Minecraft server is not running.")
            process.stdin.write(text.strip() + "\n")
            process.stdin.flush()
        self.console.add("> " + text.strip())

    def _supervise(self) -> None:
        while True:
            time.sleep(2)
            with self.lock:
                process = self.process
                if process is not None and process.poll() is not None:
                    self.last_exit = process.returncode
                    self.process = None
                    if not self.manual_stop and load_settings().get("auto_start", True):
                        delay = max(5, min(300, int(load_settings().get("restart_delay_seconds", 10))))
                        self.next_restart = time.time() + delay
                        self.console.add(f"Server exited (code {self.last_exit}); restarting in {delay}s.")
                if self.process is None and not self.manual_stop and load_settings().get("auto_start", True):
                    if self.next_restart is None:
                        self.next_restart = time.time() + 1
                    if time.time() >= self.next_restart:
                        try:
                            self._spawn()
                            self.restart_count += 1
                            self.next_restart = None
                        except Exception as exc:
                            self.console.add(f"Automatic restart failed: {exc}")
                            self.next_restart = time.time() + 30

    def status(self) -> dict:
        with self.lock:
            process = self.process
            running = process is not None and process.poll() is None
            pid = process.pid if running else None
            rss = 0
            if pid:
                try:
                    rss = psutil.Process(pid).memory_info().rss
                except (psutil.Error, OSError):
                    pass
            return {
                "running": running, "pid": pid, "last_exit": self.last_exit,
                "last_start": self.last_start, "restart_count": self.restart_count,
                "next_restart": self.next_restart,
                "ram_mb": round(rss / (1024 * 1024)),
                "cpu_percent": psutil.cpu_percent(interval=None),
                "memory_available_mb": int(psutil.virtual_memory().available / (1024 * 1024)),
                "safe_heap_mb": safe_memory_mb(),
            }


MANAGER = None
STOP_EVENT = threading.Event()
PUBLIC_CACHE = {"checked": 0.0, "ip": None, "reachable": None, "error": None}


def mc_status() -> dict:
    def varint(number: int) -> bytes:
        value = number & 0xFFFFFFFF
        result = bytearray()
        while True:
            byte = value & 0x7F
            value >>= 7
            if value:
                byte |= 0x80
            result.append(byte)
            if not value:
                return bytes(result)

    def string(value: str) -> bytes:
        encoded = value.encode()
        return varint(len(encoded)) + encoded

    def read_varint(sock: socket.socket) -> int:
        value = 0
        for index in range(5):
            byte = sock.recv(1)
            if not byte:
                raise OSError("Unexpected end of status response.")
            value |= (byte[0] & 0x7F) << (7 * index)
            if not byte[0] & 0x80:
                return value
        raise OSError("Invalid status response.")

    try:
        with socket.create_connection(("127.0.0.1", MINECRAFT_PORT), timeout=1.5) as sock:
            sock.settimeout(1.5)
            packet = varint(0) + varint(0) + string("127.0.0.1") + struct.pack(">H", MINECRAFT_PORT) + varint(1)
            sock.sendall(varint(len(packet)) + packet + b"\x01\x00")
            read_varint(sock)
            if read_varint(sock) != 0:
                raise OSError("Unexpected status packet.")
            size = read_varint(sock)
            if size > 1_000_000:
                raise OSError("Status response is too large.")
            payload = bytearray()
            while len(payload) < size:
                chunk = sock.recv(size - len(payload))
                if not chunk:
                    raise OSError("Incomplete status response.")
                payload.extend(chunk)
            info = json.loads(payload.decode("utf-8"))
            players = info.get("players", {})
            return {
                "online": True, "version": info.get("version", {}).get("name"),
                "online_players": players.get("online", 0),
                "max_players": players.get("max", 0),
                "players": [player.get("name", "") for player in players.get("sample", [])],
                "description": info.get("description", ""),
            }
    except (OSError, ValueError, json.JSONDecodeError):
        return {"online": False, "online_players": 0, "max_players": 0, "players": []}


def public_connectivity() -> dict:
    if time.time() - PUBLIC_CACHE["checked"] < 45:
        return dict(PUBLIC_CACHE)
    result = {"checked": time.time(), "ip": None, "reachable": None, "error": None}
    try:
        request = urllib.request.Request("https://api.ipify.org", headers={"User-Agent": "ServerMaker/1.0"})
        with urllib.request.urlopen(request, timeout=4) as response:
            ip = response.read(64).decode("ascii").strip()
        if not re.fullmatch(r"[0-9a-fA-F:.]+", ip):
            raise ValueError("Public IP service returned an invalid address.")
        result["ip"] = ip
        endpoints = (
            f"https://api.mcstatus.io/v2/status/java/{quote(ip, safe=':.')}:{MINECRAFT_PORT}",
            f"https://api.mcsrvstat.us/3/{quote(ip, safe=':.')}:{MINECRAFT_PORT}",
        )
        status = None
        errors = []
        for status_url in endpoints:
            try:
                request = urllib.request.Request(status_url, headers={"User-Agent": "ServerMaker/1.0"})
                with urllib.request.urlopen(request, timeout=5) as response:
                    status = json.loads(response.read(65536))
                break
            except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
                errors.append(str(exc))
        if status is None:
            raise RuntimeError("; ".join(errors))
        result["reachable"] = bool(status.get("online"))
        result["address"] = f"{ip}:{MINECRAFT_PORT}" if result["reachable"] else None
        if not result["reachable"]:
            result["error"] = "No external Minecraft connection reached this address and port."
    except (OSError, ValueError, RuntimeError, urllib.error.URLError, json.JSONDecodeError) as exc:
        result["error"] = f"Public connectivity test failed: {exc}"
    PUBLIC_CACHE.clear()
    PUBLIC_CACHE.update(result)
    return dict(result)


def resolve_server_path(relative: str) -> Path:
    candidate = (SERVER / relative).resolve()
    try:
        candidate.relative_to(SERVER.resolve())
    except ValueError as exc:
        raise ValueError("Path must stay inside the DensitySMP server directory.") from exc
    return candidate


def list_files(relative: str) -> list[dict]:
    path = resolve_server_path(relative)
    if not path.is_dir():
        raise ValueError("Requested path is not a directory.")
    result = []
    for child in sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        if child.is_symlink():
            continue
        result.append({
            "name": child.name,
            "directory": child.is_dir(),
            "size": child.stat().st_size if child.is_file() else None,
            "editable": child.is_file() and child.stat().st_size <= 2_000_000
            and child.suffix.lower() not in {".jar", ".dat", ".mca", ".gz", ".zip"},
        })
    return result


def make_backup() -> str:
    if MANAGER:
        MANAGER.command("save-all flush")
        time.sleep(2)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    destination = BACKUPS / f"DensitySMP-world-{stamp}.tar.gz"
    worlds = [SERVER / name for name in ("world", "world_nether", "world_the_end") if (SERVER / name).is_dir()]
    if not worlds:
        raise RuntimeError("No generated world directories exist yet.")
    with tarfile.open(destination, "w:gz") as archive:
        for world in worlds:
            archive.add(world, arcname=world.name, recursive=True)
    return destination.name


def json_response(handler: BaseHTTPRequestHandler, body: dict, status: int = 200) -> None:
    data = json.dumps(body).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(data)


class Handler(BaseHTTPRequestHandler):
    server_version = "ServerMaker/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[panel] {self.address_string()} {fmt % args}", flush=True)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in STATIC_FILES:
            name, content_type = STATIC_FILES[parsed.path]
            content = (ROOT / "web" / name).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)
            return
        if parsed.path == "/api/status":
            settings = load_settings()
            json_response(self, {
                "server": MANAGER.status(),
                "game": mc_status(),
                "public": public_connectivity(),
                "settings": settings,
                "server_dir": str(SERVER),
                "paper": {"version": PAPER_VERSION, "build": PAPER_BUILD, "verified": True},
            })
            return
        if parsed.path == "/api/properties":
            current = read_properties(SERVER / "server.properties")
            values = {prop["key"]: current.get(prop["key"], prop["default"]) for prop in PROPERTIES}
            json_response(self, {"schema": PROPERTIES, "values": values})
            return
        if parsed.path == "/api/activity":
            try:
                json_response(self, {"entries": activity.recent()})
            except (RuntimeError, OSError, ValueError) as exc:
                json_response(self, {"error": str(exc)}, 503)
            return
        if parsed.path == "/api/console":
            after = int(parse_qs(parsed.query).get("after", ["0"])[0])
            json_response(self, {"lines": MANAGER.console.since(after)})
            return
        if parsed.path == "/api/files":
            relative = parse_qs(parsed.query).get("path", [""])[0]
            json_response(self, {"path": relative, "files": list_files(relative)})
            return
        if parsed.path == "/api/file":
            relative = parse_qs(parsed.query).get("path", [""])[0]
            path = resolve_server_path(relative)
            if not path.is_file() or path.stat().st_size > 2_000_000:
                raise ValueError("File is missing or too large to edit.")
            json_response(self, {"path": relative, "content": path.read_text(encoding="utf-8")})
            return
        if parsed.path == "/api/plugins":
            plugins = []
            for plugin in sorted((SERVER / "plugins").glob("*.jar")):
                if not plugin.is_symlink():
                    plugins.append({"name": plugin.name, "size": plugin.stat().st_size})
            json_response(self, {"plugins": plugins})
            return
        if parsed.path == "/api/backups":
            items = [{"name": p.name, "size": p.stat().st_size} for p in sorted(BACKUPS.glob("DensitySMP-world-*.tar.gz"))]
            json_response(self, {"backups": items})
            return
        json_response(self, {"error": "Not found."}, 404)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > MAX_UPLOAD_BYTES:
            json_response(self, {"error": "Request is too large."}, 413)
            return
        try:
            payload = json.loads(self.rfile.read(length)) if length else {}
            path = urlparse(self.path).path
            if path == "/api/server/start":
                result = MANAGER.start()
            elif path == "/api/server/stop":
                result = MANAGER.stop()
            elif path == "/api/server/restart":
                result = MANAGER.restart()
            elif path == "/api/server/command":
                MANAGER.command(str(payload.get("command", "")))
                result = "Command sent."
            elif path == "/api/file":
                relative = str(payload.get("path", ""))
                target = resolve_server_path(relative)
                if not target.is_file() or target.stat().st_size > 2_000_000:
                    raise ValueError("Only existing text files up to 2 MB can be edited.")
                if target.suffix.lower() in {".jar", ".dat", ".mca", ".gz", ".zip"}:
                    raise ValueError("Binary files cannot be edited.")
                target.write_text(str(payload.get("content", "")), encoding="utf-8")
                result = "File saved."
            elif path == "/api/plugins/upload":
                name = str(payload.get("name", ""))
                if not re.fullmatch(r"[A-Za-z0-9_. -]{1,120}\.jar", name, re.IGNORECASE):
                    raise ValueError("Plugin filename must be a plain .jar filename.")
                encoded = str(payload.get("content", ""))
                if len(encoded) > MAX_UPLOAD_BYTES * 4 // 3:
                    raise ValueError("Plugin is larger than 128 MB.")
                content = base64.b64decode(encoded, validate=True)
                if not content.startswith(b"PK\x03\x04") or len(content) > MAX_UPLOAD_BYTES:
                    raise ValueError("The selected file is not a valid-size JAR/ZIP archive.")
                (SERVER / "plugins" / name).write_bytes(content)
                result = "Plugin uploaded; restart the server to load it."
            elif path == "/api/backups":
                result = f"Created backup {make_backup()}."
            elif path == "/api/settings":
                settings = load_settings()
                if "memory_mb" in payload:
                    memory = int(payload["memory_mb"])
                    if memory < 1024 or memory > safe_memory_mb():
                        raise ValueError(f"Memory must be between 1024 and {safe_memory_mb()} MiB.")
                    settings["memory_mb"] = memory
                if "auto_start" in payload:
                    settings["auto_start"] = bool(payload["auto_start"])
                if "restart_delay_seconds" in payload:
                    delay = int(payload["restart_delay_seconds"])
                    if not 5 <= delay <= 300:
                        raise ValueError("Restart delay must be between 5 and 300 seconds.")
                    settings["restart_delay_seconds"] = delay
                if "jvm_args" in payload:
                    text = str(payload["jvm_args"]).strip()
                    parse_jvm_args(text)
                    settings["jvm_args"] = text
                save_settings(settings)
                result = "Settings saved."
                if payload.get("restart_now") and MANAGER.status()["running"]:
                    result = f"Settings saved. {MANAGER.restart()}"
            elif path == "/api/properties":
                if not isinstance(payload, dict) or not payload:
                    raise ValueError("No server settings were provided.")
                values = {key: validate_property(key, raw) for key, raw in payload.items()}
                for key, value in values.items():
                    write_property(SERVER / "server.properties", key, value)
                result = f"Saved {len(values)} server setting(s). Restart the server to apply them."
            elif path == "/api/players/action":
                action = str(payload.get("action", ""))
                name = str(payload.get("name", ""))
                if action not in PLAYER_ACTIONS:
                    raise ValueError("Unknown player action.")
                if not re.fullmatch(r"[A-Za-z0-9_]{1,16}", name):
                    raise ValueError("Player names use 1-16 letters, numbers, or underscores.")
                MANAGER.command(PLAYER_ACTIONS[action].format(name=name))
                result = f"Sent {action} for {name}."
            elif path == "/api/shutdown":
                threading.Thread(target=shutdown_panel, daemon=True).start()
                result = "Panel is shutting down after gracefully stopping the Minecraft server."
            else:
                json_response(self, {"error": "Not found."}, 404)
                return
            activity.record(path.removeprefix("/api/").replace("/", "."), result)
            json_response(self, {"message": result})
        except (ValueError, RuntimeError, OSError, json.JSONDecodeError, binascii.Error) as exc:
            json_response(self, {"error": str(exc)}, 400)


def shutdown_panel() -> None:
    STOP_EVENT.set()
    if MANAGER:
        MANAGER.stop()


def main() -> int:
    ensure_layout()
    if len(sys.argv) > 1:
        action = sys.argv[1]
        if action == "--stop-server":
            return control_panel("/api/server/stop")
        if action == "--initialize":
            print(f"Initialized DensitySMP at {SERVER}")
            return 0
        if action == "--shutdown":
            return control_panel("/api/shutdown")
    global MANAGER
    ensure_layout()
    # Keep one panel/supervisor instance per workspace.
    import fcntl
    lock_handle = LOCK_FILE.open("w")
    try:
        fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("ServerMaker is already running.", file=sys.stderr)
        return 1
    PID_FILE.write_text(str(os.getpid()))
    MANAGER = ServerManager()
    httpd = ThreadingHTTPServer((PANEL_HOST, PANEL_PORT), Handler)
    httpd.daemon_threads = True
    httpd.timeout = 1
    signal.signal(signal.SIGTERM, lambda *_: STOP_EVENT.set())
    signal.signal(signal.SIGINT, lambda *_: STOP_EVENT.set())
    print(f"ServerMaker listening at http://{PANEL_HOST}:{PANEL_PORT}", flush=True)
    print(f"DensitySMP data: {SERVER}; world files are preserved on stop/restart.", flush=True)
    try:
        while not STOP_EVENT.is_set():
            httpd.handle_request()
    except KeyboardInterrupt:
        pass
    finally:
        shutdown_panel()
        httpd.server_close()
        try:
            PID_FILE.unlink()
        except FileNotFoundError:
            pass
    return 0


def control_panel(endpoint: str) -> int:
    request = urllib.request.Request(
        f"http://127.0.0.1:{PANEL_PORT}{endpoint}", data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            print(response.read().decode())
        return 0
    except urllib.error.URLError as exc:
        print(f"Panel is not running or could not be contacted: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
