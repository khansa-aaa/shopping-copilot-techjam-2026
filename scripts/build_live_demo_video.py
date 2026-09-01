#!/usr/bin/env python3
"""Build the preferred live Shopping Copilot submission video.

This script deliberately records a fresh, real loopback session.  It starts one
uvicorn child on the fixed demo port, forces the child offline, asks the
Playwright recorder for its independently verified milestone manifest, and then
aligns seven narration clips and a few transparent overlays to those milestones.

Without ``--voice-dir`` the output is a visibly labelled Samantha-TTS scratch
cut.  A submission cut requires all seven human-recorded ``01`` through ``07``
clips as .m4a or .wav files.  Nothing is uploaded or published by this builder.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Sequence


BASE_URL = "http://127.0.0.1:8765"
SERVER_PORT = 8765
EXPECTED_CATALOG_COUNT = 50_000
EXPECTED_STORYBOARD = "shopping-copilot-live-v1"
DEFAULT_FINAL_OUTPUT = "output/demo/shopping-copilot-techjam-final.mp4"
DEFAULT_SCRATCH_OUTPUT = "output/demo/shopping-copilot-techjam-live-scratch.mp4"
FALLBACK_STEM = "shopping-copilot-techjam-slide-fallback"
TARGET_MIN_SECONDS = 165.0
TARGET_MAX_SECONDS = 170.0
HARD_MAX_SECONDS = 175.0


class BuildError(RuntimeError):
    """A concise, user-actionable build failure."""


@dataclass(frozen=True, slots=True)
class Narration:
    number: str
    anchor: str
    text: str


NARRATIONS = (
    Narration(
        "01",
        "capture_started",
        "This is Shopping Copilot running locally over the official fifty-thousand-product "
        "snapshot, in Offline benchmark mode. A shopper can begin vaguely, so I’ll start "
        "by exploring men’s basketball products.",
    ),
    Narration(
        "02",
        "browse_turn_1_complete",
        "Turn one returns ten diverse products and asks one useful clarification. I add "
        "polyester as a requirement. Without restarting, the shortlist reranks, and the "
        "verified target—the Pro Club mesh basketball shorts—moves to number one.",
    ),
    Narration(
        "03",
        "product_detail_opened",
        "The detail view shows the snapshot price, rating, and why the item surfaced, while "
        "clearly labelling its art as illustrative. Expert mode exposes the remembered "
        "category and material, retrieval signals, and offline model status.",
    ),
    Narration(
        "04",
        "restarted",
        "That completes one end-to-end multi-turn session. Now I restart into a fresh "
        "scenario to demonstrate a harder behavior: changing direction without carrying "
        "stale preferences forward.",
    ),
    Narration(
        "05",
        "override_turn_1_complete",
        "The shopper starts with women’s anoraks, then adds faux fur and a drawstring "
        "closure. Those constraints change the shortlist, but the shopper decides that "
        "drawstring should no longer matter.",
    ),
    Narration(
        "06",
        "override_change_submitted",
        "Using Change direction, I replace the earlier preference with faux fur alone. The "
        "agent advances its intent generation, removes stale department and drawstring "
        "evidence, and at turn three ranks the eligible override target first.",
    ),
    Narration(
        "07",
        "expert_v2_verified",
        "Expert mode confirms intent version two and a seventy-percent override route. The "
        "same offline engine implements the official reset-and-respond contract. Across all "
        "two hundred public sessions, it scored zero point eight one five three two two, "
        "using zero model tokens and costing zero dollars.",
    ),
)


EXPECTED_EVENT_KEYS = (
    "capture_started",
    "opening_ready",
    "browse_started",
    "browse_turn_1_complete",
    "browse_refinement_submitted",
    "browse_rank_1_verified",
    "product_detail_opened",
    "expert_v1_verified",
    "restarted",
    "override_turn_1_complete",
    "override_turn_2_complete",
    "override_change_submitted",
    "override_rank_1_verified",
    "expert_v2_verified",
    "capture_completed",
)


# AppKit is used only for transparent editorial overlays.  Product interaction
# remains the untouched browser recording; these cards label verified milestones
# and the public-evaluator scope without covering the primary controls.
SWIFT_OVERLAY_RENDERER = r'''import AppKit
import Foundation

let arguments = CommandLine.arguments
guard arguments.count == 6 else {
    fputs("usage: render-overlay OUTPUT STYLE KICKER_FILE TITLE_FILE DETAIL_FILE\n", stderr)
    exit(2)
}

let width: CGFloat = 1920
let height: CGFloat = 1080

func readText(_ path: String) throws -> String {
    try String(contentsOfFile: path, encoding: .utf8).trimmingCharacters(in: .newlines)
}

func color(_ hex: String, alpha: CGFloat = 1) -> NSColor {
    var value: UInt64 = 0
    Scanner(string: hex).scanHexInt64(&value)
    return NSColor(
        calibratedRed: CGFloat((value >> 16) & 0xff) / 255,
        green: CGFloat((value >> 8) & 0xff) / 255,
        blue: CGFloat(value & 0xff) / 255,
        alpha: alpha
    )
}

func rounded(_ rect: NSRect, radius: CGFloat, fill: NSColor, stroke: NSColor? = nil) {
    let path = NSBezierPath(roundedRect: rect, xRadius: radius, yRadius: radius)
    fill.setFill()
    path.fill()
    if let stroke {
        stroke.setStroke()
        path.lineWidth = 1.5
        path.stroke()
    }
}

func drawText(_ value: String, in rect: NSRect, font: NSFont, foreground: NSColor,
              alignment: NSTextAlignment = .left) {
    let paragraph = NSMutableParagraphStyle()
    paragraph.alignment = alignment
    (value as NSString).draw(
        with: rect,
        options: [.usesLineFragmentOrigin, .usesFontLeading],
        attributes: [.font: font, .foregroundColor: foreground, .paragraphStyle: paragraph]
    )
}

do {
    let output = arguments[1]
    let style = arguments[2]
    let kicker = try readText(arguments[3])
    let title = try readText(arguments[4])
    let detail = try readText(arguments[5])
    let image = NSImage(size: NSSize(width: width, height: height))
    image.lockFocusFlipped(true)
    NSGraphicsContext.current?.cgContext.clear(CGRect(x: 0, y: 0, width: width, height: height))

    if style == "scratch" {
        let box = NSRect(x: 1160, y: 38, width: 704, height: 92)
        rounded(box, radius: 18, fill: color("6D241A", alpha: 0.93), stroke: color("F8D7C5", alpha: 0.8))
        drawText(kicker, in: NSRect(x: 1190, y: 55, width: 644, height: 26),
                 font: NSFont.monospacedSystemFont(ofSize: 18, weight: .bold), foreground: color("FFFFFF"))
        drawText(detail, in: NSRect(x: 1190, y: 86, width: 644, height: 24),
                 font: NSFont.systemFont(ofSize: 17, weight: .medium), foreground: color("FBE7DC"))
    } else if style == "closing" {
        let box = NSRect(x: 190, y: 820, width: 1540, height: 188)
        rounded(box, radius: 28, fill: color("101510", alpha: 0.94), stroke: color("F4F0E7", alpha: 0.5))
        drawText(kicker, in: NSRect(x: 240, y: 850, width: 1440, height: 26),
                 font: NSFont.monospacedSystemFont(ofSize: 18, weight: .bold), foreground: color("E9B45C"), alignment: .center)
        drawText(title, in: NSRect(x: 240, y: 886, width: 1440, height: 48),
                 font: NSFont.systemFont(ofSize: 38, weight: .bold), foreground: color("FFFFFF"), alignment: .center)
        drawText(detail, in: NSRect(x: 240, y: 948, width: 1440, height: 28),
                 font: NSFont.monospacedSystemFont(ofSize: 18, weight: .medium), foreground: color("D9E0D8"), alignment: .center)
    } else {
        let box = NSRect(x: 70, y: 846, width: 830, height: 164)
        let accent = style == "override" ? color("DBB47A") : color("E36B58")
        rounded(box, radius: 24, fill: color("101510", alpha: 0.92), stroke: color("FFFFFF", alpha: 0.45))
        accent.setFill()
        NSBezierPath(roundedRect: NSRect(x: 70, y: 846, width: 11, height: 164), xRadius: 5, yRadius: 5).fill()
        drawText(kicker, in: NSRect(x: 108, y: 869, width: 748, height: 25),
                 font: NSFont.monospacedSystemFont(ofSize: 17, weight: .bold), foreground: accent)
        drawText(title, in: NSRect(x: 108, y: 906, width: 748, height: 40),
                 font: NSFont.systemFont(ofSize: 31, weight: .bold), foreground: color("FFFFFF"))
        drawText(detail, in: NSRect(x: 108, y: 958, width: 748, height: 27),
                 font: NSFont.systemFont(ofSize: 18, weight: .medium), foreground: color("D9E0D8"))
    }

    image.unlockFocus()
    guard let tiff = image.tiffRepresentation,
          let bitmap = NSBitmapImageRep(data: tiff),
          let png = bitmap.representation(using: .png, properties: [:]) else {
        throw NSError(domain: "LiveDemoOverlay", code: 1)
    }
    try png.write(to: URL(fileURLWithPath: output), options: .atomic)
} catch {
    fputs("overlay rendering failed: \(error.localizedDescription)\n", stderr)
    exit(1)
}
'''


@dataclass(frozen=True, slots=True)
class AudioPlacement:
    number: str
    anchor: str
    start_seconds: float
    duration_seconds: float
    speed_factor: float
    path: Path
    source_path: Path | None
    source_sha256: str | None


@dataclass(frozen=True, slots=True)
class OverlayPlacement:
    kind: str
    start_seconds: float
    end_seconds: float
    path: Path


def run(
    command: Sequence[str | os.PathLike[str]],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    capture_output: bool = False,
    stdout: Any = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    rendered = [str(part) for part in command]
    try:
        return subprocess.run(
            rendered,
            cwd=cwd,
            env=env,
            check=True,
            text=True,
            capture_output=capture_output,
            stdout=stdout,
            timeout=timeout,
        )
    except FileNotFoundError as error:
        raise BuildError(f"required command is unavailable: {rendered[0]}") from error
    except subprocess.TimeoutExpired as error:
        raise BuildError(f"command timed out after {timeout:g}s: {rendered[0]}") from error
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or "").strip()
        suffix = f": {detail[-1800:]}" if detail else ""
        raise BuildError(f"command failed ({rendered[0]}){suffix}") from error


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative_path(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return f"external/{path.name}"


def require_tools(*, scratch: bool) -> dict[str, str]:
    names = ["ffmpeg", "ffprobe", "node", "swiftc"]
    if scratch:
        names.append("say")
    resolved = {name: shutil.which(name) for name in names}
    missing = [name for name, path in resolved.items() if path is None]
    if missing:
        raise BuildError("missing required local video tools: " + ", ".join(missing))
    return {name: str(path) for name, path in resolved.items()}


def require_recording_dependencies(root: Path, node: str) -> None:
    recording_dir = root / "demo" / "recording"
    package = recording_dir / "node_modules" / "playwright" / "package.json"
    if not package.is_file():
        raise BuildError(
            "live-recorder dependencies are missing; run scripts/setup_demo_recording.sh first"
        )
    try:
        installed = json.loads(package.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BuildError("the installed Playwright package metadata is unreadable") from error
    if not isinstance(installed, dict) or installed.get("version") != "1.55.1":
        raise BuildError(
            "the live recorder requires Playwright 1.55.1; run scripts/setup_demo_recording.sh"
        )

    probe = subprocess.run(
        [
            node,
            "--input-type=module",
            "-e",
            (
                "import { existsSync } from 'node:fs'; "
                "import { chromium } from 'playwright'; "
                "const executable = chromium.executablePath(); "
                "if (!existsSync(executable)) { console.error(executable); process.exit(3); }"
            ),
        ],
        cwd=recording_dir,
        text=True,
        capture_output=True,
        check=False,
    )
    if probe.returncode != 0:
        raise BuildError(
            "the locked Playwright Chromium browser is missing; "
            "run scripts/setup_demo_recording.sh first"
        )


def resolve_output(root: Path, value: str) -> Path:
    output_root = (root / "output").resolve()
    candidate = Path(value)
    path = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        path.relative_to(output_root)
    except ValueError as error:
        raise BuildError("--output must resolve inside this repository's output/ directory") from error
    if path.suffix.lower() != ".mp4":
        raise BuildError("--output must name an .mp4 file")
    return path


def ensure_port_free() -> None:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # Permit sockets left in TIME_WAIT by a prior clean shutdown. A live
        # listener still makes this bind fail, which is the occupancy we guard.
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", SERVER_PORT))
    except OSError as error:
        raise BuildError(
            f"loopback port {SERVER_PORT} is already occupied; stop that service before recording"
        ) from error
    finally:
        probe.close()


def tail_text(path: Path, limit: int = 3000) -> str:
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[-limit:]


def fetch_health() -> dict[str, Any]:
    request = urllib.request.Request(f"{BASE_URL}/api/health", headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=1.5) as response:
        if response.status != 200:
            raise BuildError(f"health endpoint returned HTTP {response.status}")
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise BuildError("health endpoint returned a non-object payload")
    return payload


def wait_for_ready(process: subprocess.Popen[Any], log_path: Path, timeout_seconds: float = 150.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_health: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            detail = tail_text(log_path)
            raise BuildError(
                f"dedicated demo server exited before becoming ready (code {process.returncode})"
                + (f": {detail}" if detail else "")
            )
        try:
            last_health = fetch_health()
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, BuildError):
            time.sleep(0.35)
            continue
        if last_health.get("status") == "ready":
            if last_health.get("catalog_count") != EXPECTED_CATALOG_COUNT:
                raise BuildError(
                    "ready server loaded the wrong catalog size: "
                    f"{last_health.get('catalog_count')} != {EXPECTED_CATALOG_COUNT}"
                )
            if last_health.get("hybrid_available") is not False:
                raise BuildError("dedicated recording server did not prove hybrid_available=false")
            return last_health
        time.sleep(0.35)
    detail = tail_text(log_path)
    raise BuildError(
        f"dedicated demo server was not ready after {timeout_seconds:.0f}s; last health={last_health}"
        + (f"; server log: {detail}" if detail else "")
    )


@contextlib.contextmanager
def dedicated_server(root: Path, python: Path, work: Path) -> Iterator[tuple[dict[str, Any], dict[str, str]]]:
    ensure_port_free()
    offline_env = os.environ.copy()
    offline_env.pop("OPENAI_API_KEY", None)
    offline_env["SHOPPING_COPILOT_OPENAI"] = "0"
    offline_env["PYTHONUNBUFFERED"] = "1"
    log_path = work / "uvicorn.log"
    log_handle = log_path.open("w", encoding="utf-8")
    process: subprocess.Popen[Any] | None = None
    try:
        # No reload/workers flag: this Popen is the uvicorn process itself.  The
        # finally block therefore terminates only the child this script created.
        process = subprocess.Popen(
            [
                str(python),
                "-m",
                "uvicorn",
                "demo.api.app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(SERVER_PORT),
                "--log-level",
                "warning",
            ],
            cwd=root,
            env=offline_env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        health = wait_for_ready(process, log_path)
        yield health, offline_env
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        log_handle.close()


def probe_json(ffprobe: str, path: Path) -> dict[str, Any]:
    result = run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration,size:stream=index,codec_type,codec_name,profile,pix_fmt,width,height,"
            "avg_frame_rate,r_frame_rate,sample_rate,channels,channel_layout",
            "-of",
            "json",
            path,
        ],
        capture_output=True,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise BuildError(f"ffprobe returned invalid JSON for {path}") from error
    if not isinstance(payload, dict):
        raise BuildError(f"ffprobe returned unexpected metadata for {path}")
    return payload


def media_duration(ffprobe: str, path: Path) -> float:
    metadata = probe_json(ffprobe, path)
    raw = metadata.get("format", {}).get("duration") if isinstance(metadata.get("format"), dict) else None
    try:
        value = float(raw)
    except (TypeError, ValueError) as error:
        raise BuildError(f"could not read media duration for {path}") from error
    if value <= 0:
        raise BuildError(f"media duration is not positive for {path}")
    return value


def frame_rate(value: Any) -> float:
    if not isinstance(value, str) or "/" not in value:
        return 0.0
    numerator, denominator = value.split("/", 1)
    try:
        return float(numerator) / float(denominator)
    except (ValueError, ZeroDivisionError):
        return 0.0


def validate_recorder_manifest(
    root: Path,
    path: Path,
    recording: Path,
    ffprobe: str,
    expected_health: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, float]]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BuildError("recorder did not produce a readable JSON manifest") from error
    if not isinstance(manifest, dict):
        raise BuildError("recorder manifest must be a JSON object")
    if manifest.get("schema_version") != 1 or manifest.get("storyboard_id") != EXPECTED_STORYBOARD:
        raise BuildError("recorder manifest schema/storyboard does not match shopping-copilot-live-v1")
    if not isinstance(manifest.get("base_url"), str) or manifest["base_url"].rstrip("/") != BASE_URL:
        raise BuildError("recorder manifest does not identify the dedicated loopback server")

    capture = manifest.get("capture")
    if not isinstance(capture, dict):
        raise BuildError("recorder manifest is missing capture metadata")
    expected_capture = {
        "target_duration_seconds": 166,
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "codec": "h264",
    }
    if any(capture.get(key) != value for key, value in expected_capture.items()):
        raise BuildError(f"recorder capture contract changed: {capture}")
    source_frames = capture.get("source_frames_received")
    changed_frames = capture.get("changed_source_frames")
    acknowledgments_started = capture.get("acknowledgments_started")
    acknowledgments_completed = capture.get("acknowledgments_completed")
    checkpoints = capture.get("change_checkpoints")
    stop_age = capture.get("source_frame_age_at_stop_seconds")
    if not isinstance(source_frames, int) or source_frames < 24:
        raise BuildError(f"recorder did not prove a live browser stream: {source_frames!r} source frames")
    if not isinstance(changed_frames, int) or changed_frames < 16:
        raise BuildError(f"recorder did not prove changing browser frames: {changed_frames!r}")
    if acknowledgments_started != source_frames or acknowledgments_completed != source_frames:
        raise BuildError("recorder did not acknowledge every CDP source frame")
    if not isinstance(stop_age, (int, float)) or isinstance(stop_age, bool) or float(stop_age) > 35:
        raise BuildError(f"recorder browser stream was stale at stop: {stop_age!r}")
    if not isinstance(checkpoints, list) or len(checkpoints) < 9:
        raise BuildError("recorder did not prove changed frames across the major storyboard scenes")
    checkpoint_hashes = {
        item.get("latest_frame_sha256")
        for item in checkpoints
        if isinstance(item, dict) and isinstance(item.get("latest_frame_sha256"), str)
    }
    if len(checkpoint_hashes) < 9:
        raise BuildError("recorder major-scene frame hashes are missing or repeated")

    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict):
        raise BuildError("recorder manifest is missing locked-input provenance")
    expected_inputs = {
        "recorder_sha256": sha256_file(root / "demo" / "recording" / "record_live_demo.mjs"),
        "package_lock_sha256": sha256_file(root / "demo" / "recording" / "package-lock.json"),
    }
    if any(inputs.get(key) != value for key, value in expected_inputs.items()):
        raise BuildError("recorder manifest does not match the checked-out recorder and lockfile")

    health = manifest.get("health")
    if not isinstance(health, dict):
        raise BuildError("recorder manifest is missing health evidence")
    required_health = {
        "status": "ready",
        "catalog_count": EXPECTED_CATALOG_COUNT,
        "max_turns": 10,
        "agent_contract": "reset/respond-v1",
        "hybrid_available": False,
    }
    if any(health.get(key) != value for key, value in required_health.items()):
        raise BuildError(f"recorder health evidence is not the required offline contract: {health}")
    if any(expected_health.get(key) != value for key, value in required_health.items()):
        raise BuildError("pre-record and recorder health evidence disagree")

    runtime = manifest.get("runtime")
    if not isinstance(runtime, dict) or runtime.get("playwright") != "1.55.1":
        raise BuildError("recorder runtime did not use the locked Playwright 1.55.1 package")

    assertions = manifest.get("assertions")
    if not isinstance(assertions, dict):
        raise BuildError("recorder manifest is missing UI assertions")
    if assertions.get("health_contract") is not True or assertions.get("offline_mode") is not True:
        raise BuildError("recorder did not prove its health contract and visible Offline mode")
    restart_session = assertions.get("restart_session")
    if not isinstance(restart_session, dict) or restart_session.get("changed_session_id") is not True:
        raise BuildError("recorder did not prove Restart created a fresh session")
    initial_session_hash = restart_session.get("initial_session_id_sha256")
    restarted_session_hash = restart_session.get("restarted_session_id_sha256")
    if not all(isinstance(value, str) and len(value) == 64 for value in (initial_session_hash, restarted_session_hash)):
        raise BuildError("recorder restart evidence is missing hashed session identifiers")
    if initial_session_hash == restarted_session_hash:
        raise BuildError("recorder restart evidence reused the original session")
    browse_rank_one = assertions.get("browse_rank_one")
    if not isinstance(browse_rank_one, dict) or (
        browse_rank_one.get("asin"), browse_rank_one.get("rank"), browse_rank_one.get("recommendation_count")
    ) != ("B071F2Z7JG", 1, 10) or browse_rank_one.get("unique_recommendations") is not True:
        raise BuildError(f"recorder did not verify browsing target rank one: {browse_rank_one!r}")
    product_detail = assertions.get("product_detail")
    if not isinstance(product_detail, dict) or (
        product_detail.get("asin") != "B071F2Z7JG" or product_detail.get("disclosure_visible") is not True
    ):
        raise BuildError(f"recorder did not verify the honest product detail: {product_detail!r}")
    expert_v1 = assertions.get("expert_v1")
    if not isinstance(expert_v1, dict) or (expert_v1.get("turn"), expert_v1.get("intent_version")) != (2, "v1"):
        raise BuildError(f"recorder did not verify browsing Expert mode: {expert_v1!r}")
    override_rank_one = assertions.get("override_rank_one")
    if not isinstance(override_rank_one, dict) or (
        override_rank_one.get("asin"), override_rank_one.get("rank"), override_rank_one.get("recommendation_count")
    ) != ("B09JG4V9ZR", 1, 10) or override_rank_one.get("unique_recommendations") is not True:
        raise BuildError(f"recorder did not verify override target rank one: {override_rank_one!r}")
    expert_v2 = assertions.get("expert_v2")
    if not isinstance(expert_v2, dict) or (
        expert_v2.get("turn"), expert_v2.get("intent_version")
    ) != (3, "v2"):
        raise BuildError(f"recorder did not verify override Expert mode: {expert_v2!r}")
    if expert_v2.get("retained") != ["Rain & Anoraks Anoraks", "Faux Fur"] or expert_v2.get("revoked") != [
        "womens",
        "Drawstring closure",
    ]:
        raise BuildError(f"recorder did not prove stale override evidence was revoked: {expert_v2!r}")
    probability = expert_v2.get("override_probability")
    if not isinstance(probability, (int, float)) or abs(float(probability) - 0.7) > 0.001:
        raise BuildError(f"recorder did not verify the 70% override route: {probability!r}")

    network = manifest.get("network")
    if not isinstance(network, dict):
        raise BuildError("recorder manifest is missing network-boundary evidence")
    if network.get("blocked_non_loopback_count") != 0 or network.get("blocked_urls") not in ([], None):
        raise BuildError(f"browser attempted non-loopback network access: {network}")

    api_exchanges = manifest.get("api_exchanges")
    if not isinstance(api_exchanges, list) or len(api_exchanges) < 7:
        raise BuildError("recorder did not retain the expected local API exchange evidence")
    creations = [
        exchange
        for exchange in api_exchanges
        if isinstance(exchange, dict)
        and exchange.get("method") == "POST"
        and exchange.get("path") == "/api/sessions"
        and exchange.get("status") == 201
    ]
    creation_hashes = [
        response.get("session_id_sha256") if isinstance((response := exchange.get("response")), dict) else None
        for exchange in creations
    ]
    if len(creations) != 2 or creation_hashes != [initial_session_hash, restarted_session_hash]:
        raise BuildError("local API evidence does not bind the initial and restarted sessions")
    serialized_exchanges = json.dumps(api_exchanges, sort_keys=True)
    if '"session_id":' in serialized_exchanges or '"request_id":' in serialized_exchanges:
        raise BuildError("recorder API evidence retained a raw session or request identifier")

    raw_events = manifest.get("events")
    if not isinstance(raw_events, list):
        raise BuildError("recorder manifest is missing milestone events")
    events: dict[str, float] = {}
    ordered_keys: list[str] = []
    last_time = -1.0
    for raw in raw_events:
        if not isinstance(raw, dict) or not isinstance(raw.get("key"), str):
            raise BuildError("recorder manifest contains a malformed event")
        key = raw["key"]
        value = raw.get("at_seconds")
        if key in events or not isinstance(value, (int, float)) or isinstance(value, bool):
            raise BuildError(f"recorder event {key!r} is duplicated or has no numeric timestamp")
        timestamp = float(value)
        if timestamp < last_time or timestamp < 0:
            raise BuildError("recorder milestone timestamps are not non-negative and ordered")
        events[key] = timestamp
        ordered_keys.append(key)
        last_time = timestamp
    if tuple(ordered_keys) != EXPECTED_EVENT_KEYS:
        raise BuildError(f"recorder event contract changed: {ordered_keys}")

    output = manifest.get("output")
    if not isinstance(output, dict):
        raise BuildError("recorder manifest is missing output evidence")
    if Path(str(output.get("path", ""))).resolve() != recording.resolve():
        raise BuildError("recorder manifest output path does not match the staged recording")
    if output.get("sha256") != sha256_file(recording):
        raise BuildError("staged recording hash does not match the recorder manifest")
    actual_duration = media_duration(ffprobe, recording)
    try:
        declared_duration = float(output.get("duration_seconds"))
    except (TypeError, ValueError) as error:
        raise BuildError("recorder manifest output duration is not numeric") from error
    if abs(actual_duration - declared_duration) > 0.25:
        raise BuildError(
            f"recorder duration evidence disagrees with ffprobe: {declared_duration:.3f}s vs {actual_duration:.3f}s"
        )
    if actual_duration >= HARD_MAX_SECONDS:
        raise BuildError(f"recording is {actual_duration:.3f}s; cuts at or above 175s are rejected")
    if not TARGET_MIN_SECONDS <= actual_duration <= TARGET_MAX_SECONDS:
        raise BuildError(
            f"recording missed the 165–170s target window: measured {actual_duration:.3f}s"
        )
    if events["capture_completed"] > actual_duration + 0.1:
        raise BuildError("capture_completed milestone falls after the recorded media")
    return manifest, events


def locate_voice_clips(voice_dir: Path | None) -> dict[str, Path]:
    if voice_dir is None:
        return {}
    if not voice_dir.is_dir():
        raise BuildError(f"--voice-dir is not a directory: {voice_dir}")
    result: dict[str, Path] = {}
    for narration in NARRATIONS:
        matches = [path for suffix in (".m4a", ".wav") if (path := voice_dir / f"{narration.number}{suffix}").is_file()]
        if len(matches) != 1:
            raise BuildError(
                f"--voice-dir must contain exactly one {narration.number}.m4a or {narration.number}.wav"
            )
        result[narration.number] = matches[0]
    return result


def generate_tts(say: str, narration: Narration, work: Path, rate: int) -> Path:
    text_path = work / f"narration-{narration.number}.txt"
    audio_path = work / f"narration-{narration.number}-tts.aiff"
    text_path.write_text(narration.text + "\n", encoding="utf-8")
    run([say, "-v", "Samantha", "-r", str(rate), "-f", text_path, "-o", audio_path])
    return audio_path


def clean_audio(ffmpeg: str, source: Path, output: Path, speed_factor: float = 1.0) -> None:
    filters = [
        "silenceremove=start_periods=1:start_duration=0.06:start_threshold=-48dB:"
        "stop_periods=0",
        "highpass=f=70",
        "lowpass=f=14000",
        "acompressor=threshold=-24dB:ratio=2:attack=20:release=180:makeup=1",
    ]
    if speed_factor > 1.0005:
        filters.append(f"atempo={speed_factor:.6f}")
    filters.extend(
        [
            "loudnorm=I=-17:TP=-2:LRA=7",
            "aresample=48000",
            "aformat=sample_fmts=s16:channel_layouts=stereo",
            "afade=t=in:st=0:d=0.10",
        ]
    )
    run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            source,
            "-vn",
            "-af",
            ",".join(filters),
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            output,
        ]
    )


def prepare_narration(
    tools: dict[str, str],
    voice_clips: dict[str, Path],
    events: dict[str, float],
    video_duration: float,
    work: Path,
    rate: int,
) -> list[AudioPlacement]:
    prepared: list[tuple[Narration, Path, Path | None, str | None, float]] = []
    for narration in NARRATIONS:
        source = voice_clips.get(narration.number)
        if source is None:
            source = generate_tts(tools["say"], narration, work, rate)
            source_for_manifest: Path | None = None
            source_hash: str | None = None
        else:
            source_for_manifest = source
            source_hash = sha256_file(source)

        first_clean = work / f"voice-{narration.number}-clean-first.wav"
        clean_audio(tools["ffmpeg"], source, first_clean)
        first_duration = media_duration(tools["ffprobe"], first_clean)
        prepared.append((narration, first_clean, source_for_manifest, source_hash, first_duration))

    def schedule(durations: list[float]) -> list[float]:
        starts: list[float] = []
        previous_end = 0.0
        for narration, duration in zip(NARRATIONS, durations, strict=True):
            # The named event is a lower bound, not a frame-number guess.  If a
            # prior sentence legitimately runs long, the next clip waits rather
            # than mixing two voices or being severed at a UI transition.
            start = max(0.15, events[narration.anchor] + 0.12, previous_end + 0.20)
            starts.append(start)
            previous_end = start + duration
        return starts

    natural_durations = [item[4] for item in prepared]
    speed_factor = 1.0
    starts = schedule(natural_durations)
    if starts[-1] + natural_durations[-1] > video_duration - 0.35:
        low, high = 1.0, 1.15
        for _ in range(24):
            candidate = (low + high) / 2
            durations = [value / candidate for value in natural_durations]
            candidate_starts = schedule(durations)
            if candidate_starts[-1] + durations[-1] <= video_duration - 0.35:
                high = candidate
            else:
                low = candidate
        speed_factor = high
        if speed_factor >= 1.1499:
            raise BuildError(
                "the seven narration clips cannot fit the verified recording with at most 15% tempo adjustment; "
                "rerecord the longest clips more concisely"
            )

    placements: list[AudioPlacement] = []
    final_durations: list[float] = []
    final_paths: list[Path] = []
    for narration, first_clean, _source_for_manifest, _source_hash, _first_duration in prepared:
        if speed_factor > 1.0005:
            cleaned = work / f"voice-{narration.number}-clean.wav"
            # Reprocess from the original source to avoid a second lossy/filtered
            # pass. TTS sources live beside their first-clean file in the stage.
            original = voice_clips.get(narration.number) or work / f"narration-{narration.number}-tts.aiff"
            clean_audio(tools["ffmpeg"], original, cleaned, speed_factor)
        else:
            cleaned = first_clean
        final_paths.append(cleaned)
        final_durations.append(media_duration(tools["ffprobe"], cleaned))

    starts = schedule(final_durations)
    if starts[-1] + final_durations[-1] > video_duration - 0.25:
        raise BuildError("normalized narration runs beyond the verified recording")
    for prepared_item, cleaned, start, final_duration in zip(
        prepared,
        final_paths,
        starts,
        final_durations,
        strict=True,
    ):
        narration, _first_clean, source_for_manifest, source_hash, _first_duration = prepared_item
        placements.append(
            AudioPlacement(
                number=narration.number,
                anchor=narration.anchor,
                start_seconds=start,
                duration_seconds=final_duration,
                speed_factor=speed_factor,
                path=cleaned,
                source_path=source_for_manifest,
                source_sha256=source_hash,
            )
        )
    return placements


def prepare_renderer(swiftc: str, work: Path) -> Path:
    source = work / "render-live-overlay.swift"
    binary = work / "render-live-overlay"
    source.write_text(SWIFT_OVERLAY_RENDERER, encoding="utf-8")
    run([swiftc, source, "-O", "-o", binary])
    return binary


def render_overlay(
    renderer: Path,
    ffmpeg: str,
    work: Path,
    *,
    name: str,
    style: str,
    kicker: str,
    title: str,
    detail: str,
) -> Path:
    values = (kicker, title, detail)
    text_paths: list[Path] = []
    for suffix, value in zip(("kicker", "title", "detail"), values, strict=True):
        path = work / f"overlay-{name}-{suffix}.txt"
        path.write_text(value + "\n", encoding="utf-8")
        text_paths.append(path)
    retina_output = work / f"overlay-{name}-retina.png"
    output = work / f"overlay-{name}.png"
    run([renderer, retina_output, style, *text_paths])
    # NSImage serializes at the current Retina backing scale. Convert the one
    # still once here instead of rescaling four large canvases on every frame.
    run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            retina_output,
            "-vf",
            "scale=1920:1080:flags=lanczos,format=rgba",
            "-frames:v",
            "1",
            output,
        ]
    )
    return output


def prepare_overlays(
    renderer: Path,
    ffmpeg: str,
    work: Path,
    events: dict[str, float],
    video_duration: float,
    scratch: bool,
) -> list[OverlayPlacement]:
    placements = [
        OverlayPlacement(
            "browse_target",
            events["browse_rank_1_verified"],
            min(events["product_detail_opened"], events["browse_rank_1_verified"] + 7.0),
            render_overlay(
                renderer,
                ffmpeg,
                work,
                name="browse-target",
                style="browse",
                kicker="VERIFIED PUBLIC TRACE",
                title="B071F2Z7JG · RANK #1",
                detail="Turn 2 · Pro Club mesh basketball shorts",
            ),
        ),
        OverlayPlacement(
            "override_target",
            events["override_rank_1_verified"],
            min(events["expert_v2_verified"], events["override_rank_1_verified"] + 7.0),
            render_overlay(
                renderer,
                ffmpeg,
                work,
                name="override-target",
                style="override",
                kicker="INTENT OVERRIDE VERIFIED",
                title="B09JG4V9ZR · RANK #1",
                detail="Turn 3 · stale drawstring evidence revoked",
            ),
        ),
        OverlayPlacement(
            "closing_metrics",
            max(events["expert_v2_verified"] + 1.0, video_duration - 11.5),
            max(0.0, video_duration - 0.15),
            render_overlay(
                renderer,
                ffmpeg,
                work,
                name="closing",
                style="closing",
                kicker="KHANSA + NAAMAN · SHOPPING COPILOT",
                title="0.815322 TECHNICAL SCORE · 200 PUBLIC SESSIONS",
                detail="0 model tokens · $0 API cost · fixed 50,000-item catalog snapshot",
            ),
        ),
    ]
    if scratch:
        placements.append(
            OverlayPlacement(
                "scratch_disclosure",
                0.0,
                video_duration,
                render_overlay(
                    renderer,
                    ffmpeg,
                    work,
                    name="scratch",
                    style="scratch",
                    kicker="SCRATCH CUT · SAMANTHA TTS",
                    title="",
                    detail="Replace all 7 narration clips before submission",
                ),
            )
        )
    for placement in placements:
        if placement.end_seconds <= placement.start_seconds:
            raise BuildError(f"recorder milestones leave no visible interval for {placement.kind}")
    return placements


def build_audio_timeline(
    ffmpeg: str,
    placements: list[AudioPlacement],
    duration: float,
    output: Path,
) -> None:
    command: list[str | os.PathLike[str]] = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    for placement in placements:
        command.extend(["-i", placement.path])
    filters: list[str] = []
    mix_inputs: list[str] = []
    for index, placement in enumerate(placements):
        delay_ms = round(placement.start_seconds * 1000)
        label = f"a{index}"
        filters.append(f"[{index}:a]adelay={delay_ms}|{delay_ms}[{label}]")
        mix_inputs.append(f"[{label}]")
    filters.append(
        "".join(mix_inputs)
        + f"amix=inputs={len(placements)}:duration=longest:normalize=0,"
        + f"alimiter=limit=0.95,apad,atrim=duration={duration:.6f}[audio]"
    )
    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[audio]",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            output,
        ]
    )
    run(command)


def compose_video(
    ffmpeg: str,
    recording: Path,
    audio: Path,
    overlays: list[OverlayPlacement],
    duration: float,
    output: Path,
) -> None:
    command: list[str | os.PathLike[str]] = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        recording,
        "-i",
        audio,
    ]
    for placement in overlays:
        command.extend(["-loop", "1", "-framerate", "30", "-i", placement.path])

    filters = ["[0:v]scale=1920:1080:flags=lanczos,fps=30,setsar=1,format=yuv420p[v0]"]
    current = "v0"
    for index, placement in enumerate(overlays, start=2):
        overlay_label = f"ov{index - 2}"
        next_label = f"v{index - 1}"
        filters.append(f"[{index}:v]format=rgba[{overlay_label}]")
        filters.append(
            f"[{current}][{overlay_label}]overlay=0:0:format=auto:"
            f"enable='between(t,{placement.start_seconds:.6f},{placement.end_seconds:.6f})'[{next_label}]"
        )
        current = next_label
    filters.append(f"[{current}]format=yuv420p[vout]")
    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[vout]",
            "-map",
            "1:a:0",
            "-t",
            f"{duration:.6f}",
            "-r",
            "30",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "18",
            "-profile:v",
            "high",
            "-level:v",
            "4.1",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            output,
        ]
    )
    run(command, timeout=900)


def srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def subtitle_chunks(text: str) -> list[str]:
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    chunks: list[str] = []
    for sentence in sentences:
        lines = textwrap.wrap(sentence, width=42, break_long_words=False, break_on_hyphens=False)
        chunks.extend("\n".join(lines[index:index + 2]) for index in range(0, len(lines), 2))
    return chunks


def write_subtitles(path: Path, placements: list[AudioPlacement]) -> list[dict[str, Any]]:
    entries: list[str] = []
    evidence: list[dict[str, Any]] = []
    cue_index = 1
    for narration, placement in zip(NARRATIONS, placements, strict=True):
        chunks = subtitle_chunks(narration.text)
        weights = [max(1, len(chunk.split())) for chunk in chunks]
        total_weight = sum(weights)
        cursor = placement.start_seconds
        clip_end = placement.start_seconds + placement.duration_seconds
        cue_texts: list[str] = []
        for chunk, weight in zip(chunks, weights, strict=True):
            end = min(clip_end, cursor + placement.duration_seconds * weight / total_weight)
            entries.append(
                f"{cue_index}\n{srt_timestamp(cursor)} --> {srt_timestamp(end)}\n{chunk}\n"
            )
            cue_texts.append(chunk.replace("\n", " "))
            cue_index += 1
            cursor = end
        reconstructed = " ".join(cue_texts).replace("  ", " ")
        if reconstructed != narration.text:
            raise BuildError(f"subtitle text no longer exactly matches narration {narration.number}")
        evidence.append(
            {
                "number": narration.number,
                "start_seconds": round(placement.start_seconds, 3),
                "end_seconds": round(clip_end, 3),
                "text": narration.text,
            }
        )
    path.write_text("\n".join(entries), encoding="utf-8")
    return evidence


def validate_final_video(ffprobe: str, ffmpeg: str, path: Path) -> dict[str, Any]:
    metadata = probe_json(ffprobe, path)
    streams = metadata.get("streams")
    if not isinstance(streams, list):
        raise BuildError("final MP4 contains no readable streams")
    video = next((item for item in streams if isinstance(item, dict) and item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if isinstance(item, dict) and item.get("codec_type") == "audio"), None)
    if not isinstance(video, dict) or video.get("codec_name") != "h264":
        raise BuildError("final MP4 video stream is not H.264")
    if (video.get("width"), video.get("height")) != (1920, 1080):
        raise BuildError("final MP4 is not 1920x1080")
    fps = frame_rate(video.get("avg_frame_rate"))
    if abs(fps - 30.0) > 0.01:
        raise BuildError(f"final MP4 is not 30fps: {video.get('avg_frame_rate')}")
    if video.get("pix_fmt") != "yuv420p":
        raise BuildError(f"final MP4 pixel format is not yuv420p: {video.get('pix_fmt')}")
    if not isinstance(audio, dict) or audio.get("codec_name") != "aac":
        raise BuildError("final MP4 audio stream is not AAC")
    if str(audio.get("sample_rate")) != "48000":
        raise BuildError(f"final MP4 audio is not 48kHz: {audio.get('sample_rate')}")
    duration = media_duration(ffprobe, path)
    if duration >= HARD_MAX_SECONDS:
        raise BuildError(f"final video is {duration:.3f}s; cuts at or above 175s are rejected")
    if not TARGET_MIN_SECONDS <= duration <= TARGET_MAX_SECONDS:
        raise BuildError(f"final video missed the 165–170s target: measured {duration:.3f}s")

    # This is intentionally a full decode, not a short ffprobe/container check.
    run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            path,
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        timeout=900,
    )
    return {
        "duration_seconds": round(duration, 3),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "video_codec": video.get("codec_name"),
        "video_profile": video.get("profile"),
        "pixel_format": video.get("pix_fmt"),
        "width": video.get("width"),
        "height": video.get("height"),
        "frame_rate": video.get("avg_frame_rate"),
        "audio_codec": audio.get("codec_name"),
        "audio_sample_rate": int(audio["sample_rate"]),
        "audio_channels": audio.get("channels"),
        "full_decode_verified": True,
    }


def generate_thumbnail(ffmpeg: str, video: Path, at_seconds: float, output: Path) -> None:
    run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{at_seconds:.3f}",
            "-i",
            video,
            "-frames:v",
            "1",
            output,
        ]
    )


def repository_provenance(root: Path) -> dict[str, Any]:
    head = run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True).stdout.strip()
    dirty = bool(run(["git", "status", "--porcelain"], cwd=root, capture_output=True).stdout.strip())
    names = (
        "agent.py",
        "starter/agent.py",
        "shopping_copilot/agent.py",
        "shopping_copilot/catalog.py",
        "shopping_copilot/openai_enhancer.py",
        "shopping_copilot/state.py",
        "demo/api/app.py",
        "demo/api/service.py",
        "demo/web/src/App.tsx",
        "demo/web/src/styles.css",
        "demo/recording/record_live_demo.mjs",
        "demo/recording/record_live_demo.test.mjs",
        "demo/recording/package.json",
        "demo/recording/package-lock.json",
        "scripts/build_live_demo_video.py",
        "scripts/setup_demo_recording.sh",
    )
    hashes = {name: sha256_file(root / name) for name in names if (root / name).is_file()}
    return {"git_head": head, "worktree_dirty": dirty, "source_sha256": hashes}


def preserve_slide_fallback(root: Path, final_path: Path, work: Path) -> dict[str, Any]:
    if not final_path.is_file():
        return {"preserved_this_build": False, "reason": "no_previous_final"}
    fallback = final_path.with_name(FALLBACK_STEM + final_path.suffix)
    if fallback.exists():
        return {
            "preserved_this_build": False,
            "reason": "fallback_already_exists",
            "path": relative_path(root, fallback),
            "sha256": sha256_file(fallback),
        }

    staged: list[tuple[Path, Path]] = []
    for suffix in (".mp4", ".png", ".srt", ".json"):
        source = final_path.with_suffix(suffix)
        if not source.is_file():
            continue
        destination = fallback.with_suffix(suffix)
        copied = work / f"fallback{suffix}"
        shutil.copy2(source, copied)
        if sha256_file(source) != sha256_file(copied):
            raise BuildError(f"could not immutably preserve previous final artifact: {source}")
        staged.append((copied, destination))
    if not staged or staged[0][1] != fallback:
        raise BuildError("previous final MP4 could not be staged as the slide fallback")
    for copied, destination in staged:
        os.replace(copied, destination)
    return {
        "preserved_this_build": True,
        "path": relative_path(root, fallback),
        "sha256": sha256_file(fallback),
        "sidecars": [relative_path(root, destination) for _, destination in staged[1:]],
    }


def promote(staged: dict[str, Path], final: dict[str, Path]) -> None:
    for key in ("video", "thumbnail", "subtitles", "manifest"):
        os.replace(staged[key], final[key])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--voice-dir",
        help="directory containing exactly 01..07 as .m4a or .wav; omit for a labelled TTS scratch cut",
    )
    parser.add_argument("--output", help="MP4 path inside output/ (defaults to final, or scratch when no voice-dir)")
    parser.add_argument("--tts-rate", type=int, default=180, help="Samantha scratch narration rate, 140–220 wpm")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    scratch = args.voice_dir is None
    default_output = DEFAULT_SCRATCH_OUTPUT if scratch else DEFAULT_FINAL_OUTPUT
    output = resolve_output(root, args.output or default_output)
    voice_dir = None
    if args.voice_dir:
        candidate = Path(args.voice_dir)
        voice_dir = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    work: Path | None = None
    try:
        if not 140 <= args.tts_rate <= 220:
            raise BuildError("--tts-rate must be between 140 and 220 words per minute")
        tools = require_tools(scratch=scratch)
        require_recording_dependencies(root, tools["node"])
        voice_clips = locate_voice_clips(voice_dir)
        recorder = root / "demo" / "recording" / "record_live_demo.mjs"
        python = root / ".venv-demo" / "bin" / "python"
        if not recorder.is_file():
            raise BuildError(f"recorder CLI is missing: {recorder}")
        if not python.is_file():
            raise BuildError(".venv-demo/bin/python is missing; run scripts/setup_local_web.sh first")
        if not (root / "demo" / "web" / "dist" / "index.html").is_file():
            raise BuildError("demo/web/dist is missing; build the frontend before recording")

        build_parent = (root / "output" / "demo").resolve()
        build_parent.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix=".live-build-", dir=build_parent))
        recording = work / "live-recording.mp4"
        recorder_manifest_path = work / "live-recording.json"

        with dedicated_server(root, python, work) as (health, offline_env):
            run(
                [
                    tools["node"],
                    recorder,
                    "--base-url",
                    BASE_URL,
                    "--output",
                    recording.resolve(),
                    "--manifest",
                    recorder_manifest_path.resolve(),
                ],
                cwd=root,
                env=offline_env,
                capture_output=True,
                timeout=420,
            )

        if not recording.is_file():
            raise BuildError("recorder completed without producing its staged MP4")
        recorder_manifest, events = validate_recorder_manifest(
            root,
            recorder_manifest_path,
            recording,
            tools["ffprobe"],
            health,
        )
        recording_duration = media_duration(tools["ffprobe"], recording)

        placements = prepare_narration(
            tools,
            voice_clips,
            events,
            recording_duration,
            work,
            args.tts_rate,
        )
        audio_timeline = work / "narration-timeline.wav"
        build_audio_timeline(tools["ffmpeg"], placements, recording_duration, audio_timeline)

        renderer = prepare_renderer(tools["swiftc"], work)
        overlays = prepare_overlays(renderer, tools["ffmpeg"], work, events, recording_duration, scratch)
        staged_video = work / "composed.mp4"
        compose_video(
            tools["ffmpeg"],
            recording,
            audio_timeline,
            overlays,
            recording_duration,
            staged_video,
        )
        media = validate_final_video(tools["ffprobe"], tools["ffmpeg"], staged_video)

        staged_thumbnail = work / "thumbnail.png"
        thumbnail_time = min(recording_duration - 1, events["browse_rank_1_verified"] + 1.0)
        generate_thumbnail(tools["ffmpeg"], staged_video, thumbnail_time, staged_thumbnail)
        staged_subtitles = work / "subtitles.srt"
        subtitle_evidence = write_subtitles(staged_subtitles, placements)

        final_paths = {
            "video": output,
            "thumbnail": output.with_suffix(".png"),
            "subtitles": output.with_suffix(".srt"),
            "manifest": output.with_suffix(".json"),
        }
        for path in final_paths.values():
            path.parent.mkdir(parents=True, exist_ok=True)

        fallback: dict[str, Any]
        if not scratch and output == (root / DEFAULT_FINAL_OUTPUT).resolve():
            fallback = preserve_slide_fallback(root, output, work)
        else:
            fallback = {"preserved_this_build": False, "reason": "not_promoting_default_final"}

        recorder_output = recorder_manifest.get("output", {})
        recorder_runtime = recorder_manifest.get("runtime")
        safe_runtime = (
            {
                key: recorder_runtime.get(key)
                for key in ("node", "playwright", "chromium", "ffmpeg", "ffprobe", "platform", "architecture", "os_release")
            }
            if isinstance(recorder_runtime, dict)
            else None
        )
        manifest = {
            "schema_version": 1,
            "builder": "scripts/build_live_demo_video.py",
            "storyboard_id": EXPECTED_STORYBOARD,
            "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
            "cut_kind": "scratch_samantha_tts" if scratch else "submission_human_voice",
            "scratch_disclosure_visible": scratch,
            "video": relative_path(root, final_paths["video"]),
            "thumbnail": relative_path(root, final_paths["thumbnail"]),
            "subtitles": relative_path(root, final_paths["subtitles"]),
            "media": media,
            "recording": {
                "schema_version": recorder_manifest.get("schema_version"),
                "storyboard_id": recorder_manifest.get("storyboard_id"),
                "capture": recorder_manifest.get("capture"),
                "health": recorder_manifest.get("health"),
                # Deliberately omit chromium_executable: it is an absolute local
                # path and adds no evidentiary value to the public sidecar.
                "runtime": safe_runtime,
                "assertions": recorder_manifest.get("assertions"),
                "network": recorder_manifest.get("network"),
                "api_exchanges": recorder_manifest.get("api_exchanges"),
                "inputs": recorder_manifest.get("inputs"),
                "events": recorder_manifest.get("events"),
                "duration_seconds": recorder_output.get("duration_seconds"),
                "size_bytes": recorder_output.get("size_bytes"),
                "video_sha256": recorder_output.get("sha256"),
                "raw_manifest_sha256": sha256_file(recorder_manifest_path),
            },
            "narration": {
                "provenance": "macOS Samantha synthetic scratch narration" if scratch else "seven user-supplied clips",
                "voice_identity_changed": False,
                "processing": "silence trim, high/low-pass, light compression, loudness normalization",
                "placements": [
                    {
                        "number": placement.number,
                        "anchor_event": placement.anchor,
                        "start_seconds": round(placement.start_seconds, 3),
                        "duration_seconds": round(placement.duration_seconds, 3),
                        "speed_factor": round(placement.speed_factor, 6),
                        "source": (
                            relative_path(root, placement.source_path)
                            if placement.source_path is not None
                            else "generated/Samantha-TTS"
                        ),
                        "source_sha256": placement.source_sha256,
                    }
                    for placement in placements
                ],
            },
            "subtitles_exact": subtitle_evidence,
            "overlays": [
                {
                    "kind": placement.kind,
                    "start_seconds": round(placement.start_seconds, 3),
                    "end_seconds": round(placement.end_seconds, 3),
                }
                for placement in overlays
            ],
            "thumbnail_at_seconds": round(thumbnail_time, 3),
            "slide_fallback": fallback,
            "repository_provenance": repository_provenance(root),
            "claims_scope": (
                "Live local offline UI interaction plus deterministic public-evaluator evidence only; "
                "fixed snapshot, no checkout, no private-set or deployment claim."
            ),
        }
        staged_manifest = work / "manifest.json"
        staged_manifest.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        staged_paths = {
            "video": staged_video,
            "thumbnail": staged_thumbnail,
            "subtitles": staged_subtitles,
            "manifest": staged_manifest,
        }
        promote(staged_paths, final_paths)
        print(
            json.dumps(
                {
                    "cut_kind": manifest["cut_kind"],
                    "video": relative_path(root, final_paths["video"]),
                    "thumbnail": relative_path(root, final_paths["thumbnail"]),
                    "subtitles": relative_path(root, final_paths["subtitles"]),
                    "manifest": relative_path(root, final_paths["manifest"]),
                    **media,
                },
                indent=2,
            )
        )
        return 0
    except BuildError as error:
        print(f"Live demo video was not built: {error}", file=sys.stderr)
        return 2
    finally:
        if work is not None:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
