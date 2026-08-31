#!/usr/bin/env python3
"""Build the final Shopping Copilot UI demo as a narrated 1080p MP4.

The builder is intentionally macOS-focused: it uses ``say`` for narration,
AppKit for deterministic slide composition, and FFmpeg for H.264/AAC encoding.
It validates every required UI capture and the documented demo evidence before
touching the final output file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT = "output/demo/shopping-copilot-techjam-final.mp4"
DEFAULT_SCREENSHOTS = "output/demo-ui"
MIN_SCREENSHOT_WIDTH = 1000
MIN_SCREENSHOT_HEIGHT = 540


class BuildError(RuntimeError):
    """A user-actionable build failure."""


@dataclass(frozen=True, slots=True)
class Segment:
    kicker: str
    title: str
    body: str
    narration: str
    accent: str
    screenshot: str | None = None


SEGMENTS = (
    Segment(
        "THE CONVERSATIONAL SEARCH PROBLEM",
        "Search that remembers the conversation",
        "50,000 products\n10-turn state\nExact-ASIN recommendations\nComplete offline path",
        "Shoppers rarely begin with a perfect query. They start broad, add must-haves, "
        "reject options, and sometimes change direction. Shopping Copilot keeps that "
        "conversation as structured state, then ranks exact catalog products. This "
        "interface and the official judge adapter use the same offline-first retrieval engine.",
        "F16F54",
        "01-opening.png",
    ),
    Segment(
        "LOCAL RETRIEVAL ARCHITECTURE",
        "Three local signals. One deterministic ranking.",
        "FIELD-WEIGHTED FTS5\nTitles, categories, features and details\n\n"
        "STRUCTURED RETRIEVAL\nCategory, material, color and brand; budget filter\n\n"
        "256D CATALOG HASH VECTORS\nA local dense intent signal; no embedding API\n\n"
        "WEIGHTED RANK FUSION\nConfidence filters and top-100 reranking",
        "At startup, Shopping Copilot builds three local retrieval signals: weighted "
        "full-text search, structured facets, and a two-hundred-fifty-six-dimensional catalog hash index. "
        "Their rankings are fused, confidence-filtered, and reranked locally. No "
        "network or model call is required for the scored path.",
        "45CDBB",
    ),
    Segment(
        "ACTUAL LOCAL UI · TURN 1",
        "Start broad. Clarify what matters.",
        "Basketball Men\n10 diverse candidates\nOne composite clarification\nOffline benchmark mode",
        "I begin broadly with basketball products. The first turn returns a diverse, "
        "explainable shortlist and asks one useful composite clarification instead of "
        "guessing. The interface keeps the privacy boundary visible: this benchmark "
        "session and its remembered preferences stay on this Mac.",
        "C7D96F",
        "02-broad-results.png",
    ),
    Segment(
        "VERIFIED PUBLIC DEMO TRACE · TURN 2",
        "One answer moves the target to rank one",
        "polyester + 100% Polyester\nB071F2Z7JG\nPro Club Men's Heavyweight\nMesh Basketball Shorts",
        "After the shopper reveals the polyester constraints, accumulated evidence "
        "moves the matching Pro Club mesh basketball shorts to rank one on turn two. "
        "The build verifies that public demo trace before rendering this video; the "
        "runtime agent itself never receives the target label.",
        "F0B63B",
        "03-rank-one.png",
    ),
    Segment(
        "ACTUAL LOCAL UI · PRODUCT DETAIL",
        "Explainable without pretending data is live",
        "Snapshot price and rating\nWhy it surfaced\nCategory art—not a product photo\nAmazon is verification only",
        "The product detail view explains why the item surfaced and labels every "
        "commerce field as snapshot data. Category art is explicitly not a product "
        "photo. The Amazon link is only for checking the current listing; Shopping "
        "Copilot does not add to cart or perform checkout.",
        "F0B63B",
        "04-product-detail.png",
    ),
    Segment(
        "ACTUAL LOCAL UI · EXPERT MODE",
        "Inspect the intent the agent remembered",
        "Route probabilities\nHard versus soft constraints\nIntent generation\nLatency and model status",
        "Expert mode exposes the route probabilities and remembered must-haves behind "
        "the shortlist. It also shows the current turn, intent generation, response "
        "time, retrieval signals, and optional-model status, so a reviewer can inspect "
        "the system without changing the official scoring contract.",
        "45CDBB",
        "05-expert.png",
    ),
    Segment(
        "ACTUAL LOCAL UI + VERIFIED TRACE · TURN 3",
        "Changed direction, visible in state",
        "Turn 3 / 10 · intent version v2\nOverride route 70%\n"
        "Only category + Faux Fur retained\nB09JG4V9ZR → rank 1 in verified trace",
        "After changing direction on turn three, Expert mode shows intent version two "
        "and a seventy-percent override route. Old department and drawstring evidence "
        "are gone; category and faux fur remain. The trace verifier confirms the new "
        "target at rank one. Boundary tombstones prevent repeated questions, and turn "
        "ten never asks again.",
        "8E7CF4",
        "08-override-expert.png",
    ),
    Segment(
        "200 PUBLIC SESSIONS · FROZEN OFFLINE CONFIGURATION",
        "Measured against the official weak baseline",
        "HITRATE@10\n0.125 → 0.985\n\n"
        "MRR\n0.068034 → 0.556740\n\n"
        "MTTC · LOWER IS BETTER\n9.81 → 3.21\n\n"
        "TECHNICAL SCORE\n0.106710 → 0.815322",
        "On the unmodified two-hundred-session public evaluator, Hit Rate at ten "
        "reached zero point nine eight five, M R R reached zero point five five six "
        "seven four zero, and mean turns to conversion fell to three point two one. "
        "Technical Score improved from zero point one zero six seven one zero to zero "
        "point eight one five three two two.",
        "F16F54",
    ),
    Segment(
        "SUBMISSION-READY LOCAL EXPERIENCE",
        "Offline first. Honest about the tradeoffs.",
        "0 model tokens · $0 API cost\n20.7 ms p50 · 55.5 ms p95\n733 MB measured peak RAM\nFixed snapshot · no checkout",
        "The frozen competition run used zero model tokens and cost zero dollars. "
        "Response latency was twenty point seven milliseconds median and fifty-five "
        "point five at p ninety-five. Peak memory was seven-hundred-thirty-three "
        "megabytes. This is a production-shaped local experience on a fixed snapshot, "
        "not a claim of live inventory or public deployment.",
        "45CDBB",
        "01-opening.png",
    ),
)


SWIFT_RENDERER = r'''import AppKit
import Foundation

let arguments = CommandLine.arguments
guard arguments.count == 10 else {
    fputs("usage: render-final OUTPUT IMAGE|- KICKER TITLE BODY ACCENT STYLE INDEX TOTAL\n", stderr)
    exit(2)
}

let width: CGFloat = 1920
let height: CGFloat = 1080
let output = arguments[1]
let imagePath = arguments[2]
let accentHex = arguments[6]
let style = arguments[7]
let index = Int(arguments[8]) ?? 1
let total = max(Int(arguments[9]) ?? 1, 1)

func readText(_ path: String) throws -> String {
    try String(contentsOfFile: path, encoding: .utf8).trimmingCharacters(in: .newlines)
}

func color(_ hex: String, alpha: CGFloat = 1) -> NSColor {
    let cleaned = hex.trimmingCharacters(in: CharacterSet(charactersIn: "#"))
    var value: UInt64 = 0
    Scanner(string: cleaned).scanHexInt64(&value)
    return NSColor(
        calibratedRed: CGFloat((value >> 16) & 0xff) / 255,
        green: CGFloat((value >> 8) & 0xff) / 255,
        blue: CGFloat(value & 0xff) / 255,
        alpha: alpha
    )
}

func drawText(
    _ value: String,
    in rect: NSRect,
    font: NSFont,
    foreground: NSColor,
    lineSpacing: CGFloat = 0,
    alignment: NSTextAlignment = .left
) {
    let paragraph = NSMutableParagraphStyle()
    paragraph.lineSpacing = lineSpacing
    paragraph.alignment = alignment
    (value as NSString).draw(
        with: rect,
        options: [.usesLineFragmentOrigin, .usesFontLeading],
        attributes: [
            .font: font,
            .foregroundColor: foreground,
            .paragraphStyle: paragraph,
        ]
    )
}

func rounded(_ rect: NSRect, radius: CGFloat, fill: NSColor, stroke: NSColor? = nil, lineWidth: CGFloat = 1) {
    let path = NSBezierPath(roundedRect: rect, xRadius: radius, yRadius: radius)
    fill.setFill()
    path.fill()
    if let stroke {
        stroke.setStroke()
        path.lineWidth = lineWidth
        path.stroke()
    }
}

do {
    let kicker = try readText(arguments[3])
    let title = try readText(arguments[4])
    let body = try readText(arguments[5])
    let accent = color(accentHex)
    let canvas = NSImage(size: NSSize(width: width, height: height))
    canvas.lockFocusFlipped(true)

    color("F4F0E7").setFill()
    NSBezierPath(rect: NSRect(x: 0, y: 0, width: width, height: height)).fill()
    color("101510").setFill()
    NSBezierPath(rect: NSRect(x: 0, y: 0, width: width, height: 92)).fill()
    accent.withAlphaComponent(0.13).setFill()
    NSBezierPath(ovalIn: NSRect(x: 1550, y: -190, width: 520, height: 520)).fill()
    color("C7B9F3", alpha: 0.16).setFill()
    NSBezierPath(ovalIn: NSRect(x: -170, y: 750, width: 470, height: 470)).fill()

    rounded(NSRect(x: 54, y: 25, width: 48, height: 48), radius: 13, fill: color("171C18"), stroke: accent, lineWidth: 2)
    drawText("SC", in: NSRect(x: 54, y: 38, width: 48, height: 24), font: NSFont.monospacedSystemFont(ofSize: 17, weight: .bold), foreground: color("FFFFFF"), alignment: .center)
    drawText("SHOPPING COPILOT", in: NSRect(x: 120, y: 27, width: 410, height: 30), font: NSFont.systemFont(ofSize: 24, weight: .bold), foreground: color("FFFFFF"))
    drawText("TECHJAM 2026", in: NSRect(x: 120, y: 57, width: 410, height: 22), font: NSFont.monospacedSystemFont(ofSize: 15, weight: .semibold), foreground: color("B8C2B9"))
    drawText("OFFLINE-FIRST · EXACT-ASIN RETRIEVAL", in: NSRect(x: 1220, y: 35, width: 620, height: 28), font: NSFont.monospacedSystemFont(ofSize: 17, weight: .semibold), foreground: color("E9EEE8"), alignment: .right)

    if style == "ui" {
        drawText(kicker, in: NSRect(x: 94, y: 154, width: 500, height: 34), font: NSFont.monospacedSystemFont(ofSize: 18, weight: .bold), foreground: color("8E3D31"))
        drawText(title, in: NSRect(x: 94, y: 205, width: 500, height: 180), font: NSFont.systemFont(ofSize: 57, weight: .bold), foreground: color("111611"), lineSpacing: -2)
        drawText(body, in: NSRect(x: 94, y: 424, width: 500, height: 355), font: NSFont.monospacedSystemFont(ofSize: 27, weight: .medium), foreground: color("303731"), lineSpacing: 15)

        guard let screenshot = NSImage(contentsOfFile: imagePath) else {
            throw NSError(domain: "FinalDemoRenderer", code: 2, userInfo: [NSLocalizedDescriptionKey: "cannot decode screenshot \(imagePath)"])
        }
        let frame = NSRect(x: 640, y: 150, width: 1185, height: 648)
        let shadow = NSShadow()
        shadow.shadowColor = color("000000", alpha: 0.22)
        shadow.shadowBlurRadius = 24
        shadow.shadowOffset = NSSize(width: 0, height: 10)
        NSGraphicsContext.saveGraphicsState()
        shadow.set()
        rounded(frame, radius: 25, fill: color("FFFFFF"))
        NSGraphicsContext.restoreGraphicsState()
        NSGraphicsContext.saveGraphicsState()
        NSBezierPath(roundedRect: frame, xRadius: 25, yRadius: 25).addClip()
        screenshot.draw(in: frame, from: .zero, operation: .sourceOver, fraction: 1, respectFlipped: true, hints: [.interpolation: NSImageInterpolation.high])
        NSGraphicsContext.restoreGraphicsState()
        rounded(frame, radius: 25, fill: color("FFFFFF", alpha: 0), stroke: color("171C18", alpha: 0.25), lineWidth: 2)

        rounded(NSRect(x: 640, y: 831, width: 1185, height: 98), radius: 20, fill: color("FFFFFF", alpha: 0.72), stroke: color("D4CFC4"), lineWidth: 1)
        drawText("ACTUAL LOCAL INTERFACE CAPTURE", in: NSRect(x: 674, y: 853, width: 520, height: 25), font: NSFont.monospacedSystemFont(ofSize: 17, weight: .bold), foreground: color("171C18"))
        drawText("Fixed 50,000-item catalog snapshot · no checkout", in: NSRect(x: 674, y: 882, width: 930, height: 24), font: NSFont.systemFont(ofSize: 19, weight: .regular), foreground: color("596158"))
    } else {
        drawText(kicker, in: NSRect(x: 130, y: 145, width: 1500, height: 34), font: NSFont.monospacedSystemFont(ofSize: 19, weight: .bold), foreground: color("8E3D31"))
        drawText(title, in: NSRect(x: 130, y: 195, width: 1660, height: 105), font: NSFont.systemFont(ofSize: 64, weight: .bold), foreground: color("111611"))
        let cards = body.components(separatedBy: "\n\n").prefix(4)
        for (offset, card) in cards.enumerated() {
            let column = offset % 2
            let row = offset / 2
            let cardRect = NSRect(x: 130 + CGFloat(column) * 835, y: 350 + CGFloat(row) * 265, width: 785, height: 220)
            rounded(cardRect, radius: 25, fill: color("FFFCF6", alpha: 0.92), stroke: color("D7D0C3"), lineWidth: 1.5)
            accent.setFill()
            NSBezierPath(roundedRect: NSRect(x: cardRect.minX, y: cardRect.minY, width: 10, height: cardRect.height), xRadius: 5, yRadius: 5).fill()
            let lines = card.components(separatedBy: "\n")
            let heading = lines.first ?? ""
            let detail = lines.dropFirst().joined(separator: "\n")
            drawText(heading, in: NSRect(x: cardRect.minX + 38, y: cardRect.minY + 31, width: cardRect.width - 72, height: 36), font: NSFont.monospacedSystemFont(ofSize: 21, weight: .bold), foreground: color("5B332D"))
            drawText(detail, in: NSRect(x: cardRect.minX + 38, y: cardRect.minY + 82, width: cardRect.width - 72, height: 105), font: NSFont.systemFont(ofSize: 31, weight: .semibold), foreground: color("171C18"), lineSpacing: 7)
        }
        drawText("Claims shown here are checked against repository evidence before encoding.", in: NSRect(x: 130, y: 900, width: 1500, height: 30), font: NSFont.systemFont(ofSize: 20, weight: .regular), foreground: color("596158"))
    }

    color("D0C9BC").setFill()
    NSBezierPath(rect: NSRect(x: 94, y: 1008, width: 1732, height: 4)).fill()
    accent.setFill()
    NSBezierPath(rect: NSRect(x: 94, y: 1008, width: 1732 * CGFloat(index) / CGFloat(total), height: 4)).fill()
    drawText("\(index) / \(total)", in: NSRect(x: 1640, y: 1025, width: 186, height: 28), font: NSFont.monospacedSystemFont(ofSize: 17, weight: .regular), foreground: color("596158"), alignment: .right)

    canvas.unlockFocus()
    guard let tiff = canvas.tiffRepresentation,
          let bitmap = NSBitmapImageRep(data: tiff),
          let png = bitmap.representation(using: .png, properties: [:]) else {
        throw NSError(domain: "FinalDemoRenderer", code: 3, userInfo: [NSLocalizedDescriptionKey: "cannot encode rendered frame"])
    }
    try png.write(to: URL(fileURLWithPath: output), options: .atomic)
} catch {
    fputs("final frame rendering failed: \(error.localizedDescription)\n", stderr)
    exit(1)
}
'''


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    capture_output: bool = False,
    stdout: Any = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            check=True,
            text=True,
            capture_output=capture_output,
            stdout=stdout,
            env=env,
        )
    except FileNotFoundError as error:
        raise BuildError(f"required command is unavailable: {command[0]}") from error
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or "").strip()
        suffix = f": {detail[-1200:]}" if detail else ""
        raise BuildError(f"command failed ({command[0]}){suffix}") from error


def require_tools() -> dict[str, str]:
    required = ("ffmpeg", "ffprobe", "say", "swiftc")
    resolved = {name: shutil.which(name) for name in required}
    missing = [name for name, path in resolved.items() if path is None]
    if missing:
        raise BuildError(
            "missing required video tools: "
            + ", ".join(missing)
            + ". This builder requires macOS say/AppKit plus FFmpeg."
        )
    return {name: str(path) for name, path in resolved.items()}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe_json(ffprobe: str, path: Path) -> dict[str, Any]:
    result = run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration,size:stream=index,codec_type,codec_name,width,height,avg_frame_rate,sample_rate,channels",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise BuildError(f"ffprobe returned invalid metadata for {path}") from error
    if not isinstance(payload, dict):
        raise BuildError(f"ffprobe returned unexpected metadata for {path}")
    return payload


def relative_manifest_path(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return f"external/{path.name}"


def validate_screenshots(ffprobe: str, screenshots_dir: Path, root: Path) -> dict[str, dict[str, Any]]:
    names = sorted({segment.screenshot for segment in SEGMENTS if segment.screenshot})
    missing = [screenshots_dir / name for name in names if not (screenshots_dir / name).is_file()]
    if missing:
        listing = "\n".join(f"  - {path}" for path in missing)
        raise BuildError(
            "required UI screenshots are missing:\n"
            f"{listing}\n"
            "Capture/export these exact views into output/demo-ui, then rerun the builder."
        )

    evidence: dict[str, dict[str, Any]] = {}
    for name in names:
        path = screenshots_dir / name
        try:
            metadata = probe_json(ffprobe, path)
        except BuildError as error:
            raise BuildError(f"UI screenshot is not decodable: {path}. {error}") from error
        streams = metadata.get("streams")
        video = next(
            (item for item in streams if isinstance(item, dict) and item.get("codec_type") == "video"),
            None,
        ) if isinstance(streams, list) else None
        if not video:
            raise BuildError(f"UI screenshot has no readable image stream: {path}")
        width = video.get("width")
        height = video.get("height")
        if not isinstance(width, int) or not isinstance(height, int):
            raise BuildError(f"UI screenshot dimensions could not be read: {path}")
        if width < MIN_SCREENSHOT_WIDTH or height < MIN_SCREENSHOT_HEIGHT:
            raise BuildError(
                f"UI screenshot is too small for legible 1080p composition: {path} "
                f"is {width}x{height}; need at least {MIN_SCREENSHOT_WIDTH}x{MIN_SCREENSHOT_HEIGHT}."
            )
        evidence[name] = {
            "path": relative_manifest_path(root, path),
            "width": width,
            "height": height,
            "sha256": sha256_file(path),
            "modified_ns": path.stat().st_mtime_ns,
        }
    return evidence


def freeze_screenshots(
    screenshots_dir: Path,
    frozen_dir: Path,
    evidence: dict[str, dict[str, Any]],
) -> None:
    frozen_dir.mkdir(parents=True, exist_ok=False)
    for name, metadata in evidence.items():
        source = screenshots_dir / name
        destination = frozen_dir / name
        shutil.copy2(source, destination)
        copied_hash = sha256_file(destination)
        if copied_hash != metadata["sha256"]:
            raise BuildError(
                f"UI screenshot changed while inputs were being frozen: {source}. "
                "Stop the capture process and rerun the builder."
            )


def verify_repository_evidence(root: Path, trace_output: Path) -> dict[str, Any]:
    required = (
        root / "data" / "catalog.jsonl",
        root / "data" / "public_set.jsonl",
        root / "docs" / "baseline_results.json",
        root / "docs" / "technical_report.md",
    )
    missing = [path for path in required if not path.is_file()]
    if missing:
        raise BuildError(
            "cannot verify video claims because repository evidence is missing:\n"
            + "\n".join(f"  - {path}" for path in missing)
        )

    offline_env = os.environ.copy()
    offline_env.pop("OPENAI_API_KEY", None)
    offline_env["SHOPPING_COPILOT_OPENAI"] = "0"
    with trace_output.open("w", encoding="utf-8") as handle:
        run([sys.executable, "-m", "demos.run_demos"], cwd=root, stdout=handle, env=offline_env)
    try:
        traces = json.loads(trace_output.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise BuildError("deterministic demo verification returned invalid JSON") from error
    if not isinstance(traces, list):
        raise BuildError("deterministic demo verification returned an unexpected payload")

    expected = {
        "public_0006": ("browsing", "B071F2Z7JG", 2, 1),
        "public_0072": ("intent_override", "B09JG4V9ZR", 3, 1),
        "public_0131": ("boundary", "B07PQQQ8ZL", 2, 2),
        "public_0149": ("buying", "B07CBYYHTL", 2, 2),
    }
    indexed = {item.get("sample_id"): item for item in traces if isinstance(item, dict)}
    if set(indexed) != set(expected):
        raise BuildError(f"demo trace set changed; found {sorted(str(value) for value in indexed)}")
    verified_traces: dict[str, dict[str, Any]] = {}
    for sample_id, wanted in expected.items():
        trace = indexed[sample_id]
        turns = trace.get("turns")
        final_turn = turns[-1] if isinstance(turns, list) and turns and isinstance(turns[-1], dict) else {}
        actual = (
            trace.get("scenario"),
            trace.get("target"),
            final_turn.get("turn"),
            final_turn.get("verified_target_rank"),
        )
        if actual != wanted:
            raise BuildError(f"demo evidence changed for {sample_id}: {actual} != {wanted}")
        verified_traces[sample_id] = {
            "scenario": wanted[0],
            "target": wanted[1],
            "final_turn": wanted[2],
            "final_rank": wanted[3],
        }
    boundary_turns = indexed["public_0131"].get("turns")
    if not isinstance(boundary_turns, list) or len(boundary_turns) < 2:
        raise BuildError("boundary trace no longer contains two verified turns")
    if boundary_turns[0].get("ask_attribute") != "other" or boundary_turns[1].get("ask_attribute") == "other":
        raise BuildError("boundary trace no longer proves that the no-preference question is not repeated")

    baseline = json.loads((root / "docs" / "baseline_results.json").read_text(encoding="utf-8"))
    expected_baseline = {
        "sample_count": 200,
        "hit_rate_at_10": 0.125,
        "mrr": 0.068034,
        "mttc": 9.81,
        "technical_score": 0.10671,
    }
    if any(baseline.get(key) != value for key, value in expected_baseline.items()):
        raise BuildError("documented weak-baseline evidence changed; review the final-video claims")

    evaluator_result = run(
        [
            sys.executable,
            "-m",
            "evaluator.local_evaluator",
            "--output",
            str(trace_output.with_name("all-public-results.json")),
        ],
        cwd=root,
        capture_output=True,
        env=offline_env,
    )
    try:
        public_metrics = json.loads(evaluator_result.stdout)
    except json.JSONDecodeError as error:
        raise BuildError("the all-public evaluator returned invalid JSON") from error
    expected_final_metrics = {
        "sample_count": 200,
        "hit_rate_at_10": 0.985,
        "mrr": 0.55674,
        "mttc": 3.21,
        "recommended_technical_score": 0.815322,
    }
    if not isinstance(public_metrics, dict) or any(
        public_metrics.get(key) != value for key, value in expected_final_metrics.items()
    ):
        raise BuildError("the rerun all-public metrics changed; review the final-video claims")
    token_usage = public_metrics.get("reported_token_usage")
    if not isinstance(token_usage, dict) or any(token_usage.get(key) != 0 for key in ("prompt_tokens", "completion_tokens", "total_tokens")):
        raise BuildError("the rerun all-public evaluator was not a zero-token offline run")

    report = (root / "docs" / "technical_report.md").read_text(encoding="utf-8")
    required_report_rows = (
        "| HitRate@10 | 0.125000 | 0.985000 | +0.860000 |",
        "| MRR | 0.068034 | 0.556740 | +0.488706 |",
        "| MTTC | 9.810000 | 3.210000 | -6.600000 |",
        "| TechnicalScore | 0.106710 | 0.815322 | +0.708612 |",
        "| Response latency p50 | 20.677 ms |",
        "| Response latency p95 | 55.521 ms |",
        "| Peak RAM | 732.828 MB |",
        "| Prompt tokens | 0 |",
        "| Completion tokens | 0 |",
        "| Actual API cost | $0.00 |",
    )
    missing_rows = [row for row in required_report_rows if row not in report]
    if missing_rows:
        raise BuildError(
            "documented final evidence changed; review these video claims before rebuilding:\n"
            + "\n".join(f"  - {row}" for row in missing_rows)
        )
    return {
        "demo_traces": verified_traces,
        "baseline": expected_baseline,
        "final_public_metrics": {
            "sample_count": 200,
            "hit_rate_at_10": 0.985,
            "mrr": 0.556740,
            "mttc": 3.21,
            "technical_score": 0.815322,
            "response_latency_p50_ms": 20.677,
            "response_latency_p95_ms": 55.521,
            "peak_ram_mb": 732.828,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "actual_api_cost_usd": 0.0,
        },
        "verification": {
            "mode": "offline_forced",
            "all_public_evaluator": "rerun_during_build",
            "all_public_result_sha256": hashlib.sha256(
                json.dumps(public_metrics, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "catalog_sha256": sha256_file(root / "data" / "catalog.jsonl"),
            "public_set_sha256": sha256_file(root / "data" / "public_set.jsonl"),
            "evaluation_config_sha256": sha256_file(root / "docs" / "evaluation_config.json"),
        },
    }


def repository_provenance(root: Path) -> dict[str, Any]:
    head = run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True).stdout.strip()
    status = run(["git", "status", "--porcelain"], cwd=root, capture_output=True).stdout
    source_names = (
        "agent.py",
        "starter/agent.py",
        "shopping_copilot/agent.py",
        "shopping_copilot/catalog.py",
        "shopping_copilot/openai_enhancer.py",
        "shopping_copilot/state.py",
        "demo/api/app.py",
        "demo/api/enrichment.py",
        "demo/api/marketplaces.py",
        "demo/api/service.py",
        "demo/web/src/App.tsx",
        "demo/web/src/api.ts",
        "demo/web/src/styles.css",
        "demo/web/src/types.ts",
    )
    source_hashes: dict[str, str] = {}
    for name in source_names:
        path = root / name
        if path.is_file():
            source_hashes[name] = sha256_file(path)
    return {
        "git_head": head,
        "worktree_dirty": bool(status.strip()),
        "source_sha256": source_hashes,
    }


def srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_subtitles(path: Path, durations: list[float]) -> None:
    entries: list[str] = []
    cursor = 0.0
    index = 1
    for segment, duration in zip(SEGMENTS, durations, strict=True):
        sentences = [value.strip() for value in re.split(r"(?<=[.!?])\s+", segment.narration) if value.strip()]
        cues = [
            "\n".join(lines[index:index + 2])
            for sentence in sentences
            for lines in [textwrap.wrap(sentence, width=44, break_long_words=False, break_on_hyphens=False)]
            for index in range(0, len(lines), 2)
        ]
        weights = [max(1, len(cue.split())) for cue in cues]
        usable_start = cursor + 0.2
        usable_end = cursor + max(0.4, duration - 0.45)
        usable_duration = max(0.2, usable_end - usable_start)
        total_weight = sum(weights)
        sentence_start = usable_start
        for cue, weight in zip(cues, weights, strict=True):
            sentence_end = sentence_start + usable_duration * weight / total_weight
            entries.append(
                f"{index}\n{srt_timestamp(sentence_start)} --> {srt_timestamp(sentence_end)}\n{cue}\n"
            )
            index += 1
            sentence_start = sentence_end
        cursor += duration
    path.write_text("\n".join(entries), encoding="utf-8")


def prepare_renderer(swiftc: str, work: Path) -> Path:
    source = work / "render-final.swift"
    binary = work / "render-final"
    source.write_text(SWIFT_RENDERER, encoding="utf-8")
    run([swiftc, str(source), "-O", "-o", str(binary)])
    return binary


def media_duration(ffprobe: str, path: Path) -> float:
    metadata = probe_json(ffprobe, path)
    raw = metadata.get("format", {}).get("duration") if isinstance(metadata.get("format"), dict) else None
    try:
        return float(raw)
    except (TypeError, ValueError) as error:
        raise BuildError(f"could not read duration for {path}") from error


def build_segment(
    segment: Segment,
    *,
    index: int,
    total: int,
    root: Path,
    screenshots_dir: Path,
    work: Path,
    renderer: Path,
    tools: dict[str, str],
    voice: str,
    rate: int,
) -> tuple[Path, float]:
    prefix = f"{index:02d}"
    kicker_path = work / f"{prefix}-kicker.txt"
    title_path = work / f"{prefix}-title.txt"
    body_path = work / f"{prefix}-body.txt"
    narration_path = work / f"{prefix}-narration.txt"
    audio_path = work / f"{prefix}.aiff"
    frame_path = work / f"{prefix}.png"
    video_path = work / f"{prefix}.mp4"
    kicker_path.write_text(segment.kicker + "\n", encoding="utf-8")
    title_path.write_text(segment.title + "\n", encoding="utf-8")
    body_path.write_text(segment.body + "\n", encoding="utf-8")
    narration_path.write_text(segment.narration + "\n", encoding="utf-8")

    run([tools["say"], "-v", voice, "-r", str(rate), "-f", str(narration_path), "-o", str(audio_path)])
    screenshot_path = screenshots_dir / segment.screenshot if segment.screenshot else Path("-")
    run(
        [
            str(renderer),
            str(frame_path),
            str(screenshot_path),
            str(kicker_path),
            str(title_path),
            str(body_path),
            segment.accent,
            "ui" if segment.screenshot else "evidence",
            str(index),
            str(total),
        ],
        cwd=root,
    )

    segment_duration = media_duration(tools["ffprobe"], audio_path) + 0.9
    fade_out = max(0.55, segment_duration - 0.42)
    video_filter = (
        "scale=1920:1080:flags=lanczos,"
        "zoompan=z='min(zoom+0.000055,1.018)':"
        "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1920x1080:fps=30,"
        f"fade=t=in:st=0:d=0.28,fade=t=out:st={fade_out:.3f}:d=0.38,format=yuv420p"
    )
    audio_filter = (
        "highpass=f=65,lowpass=f=12000,"
        "loudnorm=I=-16:TP=-1.5:LRA=7,"
        f"afade=t=in:st=0:d=0.16,afade=t=out:st={fade_out:.3f}:d=0.30,apad"
    )
    run(
        [
            tools["ffmpeg"],
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-loop",
            "1",
            "-framerate",
            "30",
            "-i",
            str(frame_path),
            "-i",
            str(audio_path),
            "-vf",
            video_filter,
            "-af",
            audio_filter,
            "-t",
            f"{segment_duration:.3f}",
            "-r",
            "30",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "19",
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
            str(video_path),
        ]
    )
    return video_path, segment_duration


def verify_final_video(ffprobe: str, path: Path) -> dict[str, Any]:
    metadata = probe_json(ffprobe, path)
    streams = metadata.get("streams")
    if not isinstance(streams, list):
        raise BuildError("final MP4 contains no readable streams")
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if not isinstance(video, dict) or video.get("codec_name") != "h264":
        raise BuildError("final MP4 video stream is not H.264")
    if (video.get("width"), video.get("height")) != (1920, 1080):
        raise BuildError(f"final MP4 is not 1920x1080: {video.get('width')}x{video.get('height')}")
    if not isinstance(audio, dict) or audio.get("codec_name") != "aac":
        raise BuildError("final MP4 audio stream is not AAC")
    if str(audio.get("sample_rate")) != "48000":
        raise BuildError(f"final MP4 audio is not 48 kHz: {audio.get('sample_rate')}")
    duration = media_duration(ffprobe, path)
    if not 30 < duration < 180:
        raise BuildError(f"final video duration must be under three minutes; measured {duration:.3f}s")
    return {
        "duration_seconds": round(duration, 3),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "video_codec": video.get("codec_name"),
        "width": video.get("width"),
        "height": video.get("height"),
        "frame_rate": video.get("avg_frame_rate"),
        "audio_codec": audio.get("codec_name"),
        "audio_sample_rate": int(audio["sample_rate"]),
        "audio_channels": audio.get("channels"),
    }


def resolve_output(root: Path, value: str) -> Path:
    output_root = (root / "output").resolve()
    path = (root / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
    try:
        path.relative_to(output_root)
    except ValueError as error:
        raise BuildError("--output must resolve inside this repository's output/ directory") from error
    if path.suffix.lower() != ".mp4":
        raise BuildError("--output must name an .mp4 file")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voice", default="Samantha", help="installed macOS say voice (default: Samantha)")
    parser.add_argument("--rate", type=int, default=180, help="macOS say words per minute, 120-240")
    parser.add_argument("--screenshots-dir", default=DEFAULT_SCREENSHOTS)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check-inputs",
        action="store_true",
        help="validate tools, UI captures, and evidence without encoding video",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    screenshots_dir = (
        (root / args.screenshots_dir).resolve()
        if not Path(args.screenshots_dir).is_absolute()
        else Path(args.screenshots_dir).resolve()
    )
    build_root: Path | None = None
    try:
        if not 120 <= args.rate <= 240:
            raise BuildError("--rate must be between 120 and 240 words per minute")
        tools = require_tools()
        screenshots = validate_screenshots(tools["ffprobe"], screenshots_dir, root)
        final_path = resolve_output(root, args.output)
        build_parent = (root / "output" / "demo").resolve()
        build_parent.mkdir(parents=True, exist_ok=True)
        build_root = Path(tempfile.mkdtemp(prefix=".final-build-", dir=build_parent))
        evidence_temp = build_root / "verified-traces.json"
        evidence = verify_repository_evidence(root, evidence_temp)
        if args.check_inputs:
            print(json.dumps({"status": "ready", "screenshots": screenshots, "evidence": evidence}, indent=2))
            return 0

        frozen_screenshots_dir = build_root / "screenshots"
        freeze_screenshots(screenshots_dir, frozen_screenshots_dir, screenshots)

        renderer = prepare_renderer(tools["swiftc"], build_root)
        videos: list[Path] = []
        segment_durations: list[float] = []
        for index, segment in enumerate(SEGMENTS, 1):
            video, segment_duration = build_segment(
                segment,
                index=index,
                total=len(SEGMENTS),
                root=root,
                screenshots_dir=frozen_screenshots_dir,
                work=build_root,
                renderer=renderer,
                tools=tools,
                voice=args.voice,
                rate=args.rate,
            )
            videos.append(video)
            segment_durations.append(segment_duration)

        concat_path = build_root / "concat.txt"
        concat_path.write_text(
            "".join(f"file '{path.resolve()}'\n" for path in videos),
            encoding="utf-8",
        )
        staged_video = build_root / "shopping-copilot-techjam-final.mp4"
        run(
            [
                tools["ffmpeg"],
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_path),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(staged_video),
            ]
        )
        media = verify_final_video(tools["ffprobe"], staged_video)

        staged_thumbnail = build_root / "shopping-copilot-techjam-final.png"
        run(
            [
                tools["ffmpeg"],
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                "1",
                "-i",
                str(staged_video),
                "-frames:v",
                "1",
                str(staged_thumbnail),
            ]
        )

        final_path.parent.mkdir(parents=True, exist_ok=True)
        thumbnail_path = final_path.with_suffix(".png")
        subtitles_path = final_path.with_suffix(".srt")
        manifest_path = final_path.with_suffix(".json")
        staged_subtitles = build_root / "shopping-copilot-techjam-final.srt"
        write_subtitles(staged_subtitles, segment_durations)
        manifest = {
            "schema_version": 1,
            "video": relative_manifest_path(root, final_path),
            "thumbnail": relative_manifest_path(root, thumbnail_path),
            "subtitles": relative_manifest_path(root, subtitles_path),
            "media": media,
            "segments": [
                {
                    "index": index,
                    "kicker": segment.kicker,
                    "title": segment.title,
                    "screenshot": segment.screenshot,
                    "duration_seconds": round(segment_durations[index - 1], 3),
                }
                for index, segment in enumerate(SEGMENTS, 1)
            ],
            "screenshot_inputs": screenshots,
            "repository_provenance": repository_provenance(root),
            "evidence": evidence,
            "claims_scope": "Public-evaluator and deterministic demo evidence only; no private-set or deployment claim.",
        }
        staged_manifest = build_root / "shopping-copilot-techjam-final.json"
        staged_manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

        os.replace(staged_video, final_path)
        os.replace(staged_thumbnail, thumbnail_path)
        os.replace(staged_subtitles, subtitles_path)
        os.replace(staged_manifest, manifest_path)
        print(json.dumps({
            "video": relative_manifest_path(root, final_path),
            "thumbnail": relative_manifest_path(root, thumbnail_path),
            "subtitles": relative_manifest_path(root, subtitles_path),
            "manifest": relative_manifest_path(root, manifest_path),
            **media,
        }, indent=2))
        return 0
    except BuildError as error:
        print(f"Final demo video was not built: {error}", file=sys.stderr)
        return 2
    finally:
        if build_root is not None:
            shutil.rmtree(build_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
