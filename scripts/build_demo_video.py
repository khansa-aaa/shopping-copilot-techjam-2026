#!/usr/bin/env python3
"""Build the narrated Shopping Copilot demo video with local macOS/FFmpeg tools."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Segment:
    title: str
    body: str
    narration: str
    accent: str


SEGMENTS = (
    Segment(
        "Shopping Copilot",
        "VAGUE QUERY  ->  NEW CONSTRAINT  ->  REJECTION  ->  OVERRIDE\n\n"
        "Ordinary keyword search loses the conversation\n\n"
        "OFFLINE-FIRST CONVERSATIONAL SEARCH\n"
        "50,000 products  |  10 turns  |  Exact ASIN scoring\n\n"
        "TikTok TechJam 2026",
        "Shoppers rarely begin with a perfect query. They add constraints, reject options, and sometimes change direction. Ordinary keyword search loses that conversation. Shopping Copilot reduces repeated searching and scrolling by finding the exact catalog product as early and as highly ranked as possible.",
        "35D0BA",
    ),
    Segment(
        "Three local retrieval routes",
        "FIELD-WEIGHTED SQLITE FTS5\n"
        "Titles, categories, features, details\n\n"
        "STRUCTURED FACETS\n"
        "Material, color, brand, category, budget\n\n"
        "256D CATALOG-DERIVED HASH VECTORS\n\n"
        "Fixed weighted rank fusion -> top-100 rerank",
        "At startup, the agent builds three offline indexes over fifty thousand products: weighted full-text search, structured facets, and a catalog-derived dense feature-hash index. Evidence activates the relevant routes. Their rankings are fused, confidence-filtered, and reranked locally.",
        "7C5CFC",
    ),
    Segment(
        "End-to-end trace: vague to rank one",
        "$ python3 -m demos.run_demos\n\n"
        "public_0006 / BROWSING / VERIFIED DURING THIS BUILD\n\n"
        "T1 CUSTOMER  Basketball Men, still exploring\n"
        "T1 AGENT     asks type/use, material/color, fit, brand, budget\n"
        "T1 RESULT    target absent from top 10\n\n"
        "T2 CUSTOMER  polyester; 100% Polyester\n"
        "T2 TOP 1     B071F2Z7JG\n"
        "             Pro Club Men's Heavyweight Mesh Basketball Shorts\n\n"
        "TARGET -> RANK 1 ON TURN 2",
        "This is an end-to-end trace executed and checked during the video build. The customer begins broadly with basketball products. The agent returns a diverse shortlist and one composite clarification. After the customer reveals polyester constraints, accumulated evidence retrieves the matching mesh basketball shorts at rank one on turn two.",
        "F59E0B",
    ),
    Segment(
        "Intent override: stale evidence revoked",
        "TURN 1  Women's anorak + earlier preference\n"
        "TURN 2  Faux fur + drawstring preference\n\n"
        "TURN 3\n"
        "Actually, ignore my earlier preference.\n"
        "What I need is: Faux Fur.\n\n"
        "Intent generation advances\n"
        "Old evidence and exclusions clear\n\n"
        "VERIFIED TARGET B09JG4V9ZR -> RANK 1",
        "This session starts with an older preference. When the customer explicitly changes direction, the agent advances its intent generation, revokes prior non-category evidence, clears old exclusions, and ranks the new target first.",
        "FB7185",
    ),
    Segment(
        "Boundary behavior and contract safety",
        "'I don't have a preference for other.'\n\n"
        "NO-PREFERENCE TOMBSTONE\n"
        "The agent does not repeat the question\n\n"
        "CANDIDATE ROTATION\n"
        "Previously rejected products move behind unseen options\n\n"
        "STRICT VALIDATION\n"
        "Unique catalog IDs  |  Max 10  |  No question on turn 10\n\n"
        "VERIFIED TARGET B07PQQQ8ZL -> RANK 2",
        "For no-preference answers, tombstones prevent repeated questions. Candidate rotation avoids showing the same failed shortlist, while deterministic validation guarantees unique catalog-valid recommendations and no question on turn ten.",
        "22C55E",
    ),
    Segment(
        "Measured on the official public evaluator",
        "                         BASELINE     SHOPPING COPILOT\n\n"
        "HitRate at 10              0.125          0.985\n"
        "MRR                        0.068034       0.556740\n"
        "MTTC                       9.81           3.21\n"
        "TechnicalScore             0.106710       0.815322\n\n"
        "Response latency           20.7 ms p50 / 55.5 ms p95",
        "On the unmodified two-hundred-session public evaluator, Technical Score improved from zero point one zero six seven one zero to zero point eight one five three two two, with zero point nine eight five Hit Rate, zero point five five six seven four zero M R R, and three point two one mean turns to conversion. Median response latency was twenty point seven milliseconds.",
        "35D0BA",
    ),
    Segment(
        "Practical impact, offline by default",
        "FROZEN COMPETITION CONFIGURATION\n\n"
        "Fully offline\n"
        "Python standard library only\n"
        "0 model tokens\n"
        "$0.00 API cost\n"
        "Deterministic fallback\n\n"
        "Fewer repeated queries and less catalog scrolling\n\n"
        "Tradeoff: 733 MB peak RAM\n\n"
        "PUBLIC EVALUATOR RESULTS ONLY",
        "The frozen configuration is fully offline, used zero model tokens, and cost zero dollars, so it remains reliable when judging has no network. By resolving vague or changing intent in fewer turns, it can reduce repeated queries and catalog scrolling. Its main tradeoff is seven hundred thirty-three megabytes of peak memory. On the public evaluator, disciplined state, retrieval, and clarification dramatically outperformed the official weak baseline.",
        "7C5CFC",
    ),
)


SWIFT_RENDERER = r'''import AppKit
import Foundation

let arguments = CommandLine.arguments
guard arguments.count == 7 else {
    fputs("usage: render-slide OUTPUT TITLE_FILE BODY_FILE ACCENT INDEX TOTAL\n", stderr)
    exit(2)
}

let width: CGFloat = 1920
let height: CGFloat = 1080
let output = arguments[1]

func readText(_ path: String) throws -> String {
    return try String(contentsOfFile: path, encoding: .utf8)
        .trimmingCharacters(in: .newlines)
}

func color(_ hex: String) -> NSColor {
    let cleaned = hex.trimmingCharacters(in: CharacterSet(charactersIn: "#"))
    var value: UInt64 = 0
    Scanner(string: cleaned).scanHexInt64(&value)
    return NSColor(
        calibratedRed: CGFloat((value >> 16) & 0xff) / 255,
        green: CGFloat((value >> 8) & 0xff) / 255,
        blue: CGFloat(value & 0xff) / 255,
        alpha: 1
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

do {
    let title = try readText(arguments[2])
    let body = try readText(arguments[3])
    let accent = color(arguments[4])
    let index = Int(arguments[5]) ?? 1
    let total = max(Int(arguments[6]) ?? 1, 1)
    let lineCount = body.components(separatedBy: "\n").count
    let bodySize: CGFloat = lineCount > 12 ? 31 : (lineCount > 9 ? 34 : 38)

    let image = NSImage(size: NSSize(width: width, height: height))
    image.lockFocusFlipped(true)

    color("0B1020").setFill()
    NSBezierPath(rect: NSRect(x: 0, y: 0, width: width, height: height)).fill()
    accent.setFill()
    NSBezierPath(rect: NSRect(x: 0, y: 0, width: 24, height: height)).fill()

    color("334155").setFill()
    NSBezierPath(rect: NSRect(x: 140, y: 950, width: 1640, height: 5)).fill()
    accent.setFill()
    NSBezierPath(
        rect: NSRect(x: 140, y: 950, width: 1640 * CGFloat(index) / CGFloat(total), height: 5)
    ).fill()

    drawText(
        "SHOPPING COPILOT  /  TECHJAM 2026",
        in: NSRect(x: 140, y: 68, width: 1300, height: 44),
        font: NSFont.systemFont(ofSize: 26, weight: .semibold),
        foreground: color("A5B4FC")
    )
    drawText(
        title,
        in: NSRect(x: 140, y: 124, width: 1640, height: 100),
        font: NSFont.systemFont(ofSize: 68, weight: .bold),
        foreground: color("FFFFFF")
    )
    drawText(
        body,
        in: NSRect(x: 140, y: 272, width: 1640, height: 635),
        font: NSFont.monospacedSystemFont(ofSize: bodySize, weight: .regular),
        foreground: color("E2E8F0"),
        lineSpacing: lineCount > 12 ? 9 : 14
    )
    drawText(
        "\(index) / \(total)",
        in: NSRect(x: 1600, y: 982, width: 180, height: 42),
        font: NSFont.monospacedSystemFont(ofSize: 24, weight: .regular),
        foreground: color("94A3B8"),
        alignment: .right
    )

    image.unlockFocus()
    guard let tiff = image.tiffRepresentation,
          let bitmap = NSBitmapImageRep(data: tiff),
          let png = bitmap.representation(using: .png, properties: [:]) else {
        throw NSError(domain: "SlideRenderer", code: 1)
    }
    try png.write(to: URL(fileURLWithPath: output), options: .atomic)
} catch {
    fputs("slide rendering failed: \(error)\n", stderr)
    exit(1)
}
'''


def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=True, **kwargs)


def duration(path: Path) -> float:
    result = run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def prepare_renderer(work: Path) -> Path:
    source = work / "render-slide.swift"
    binary = work / "render-slide"
    source.write_text(SWIFT_RENDERER, encoding="utf-8")
    run(["swiftc", str(source), "-o", str(binary)])
    return binary


def verify_traces(root: Path, output: Path) -> None:
    with output.open("w", encoding="utf-8") as handle:
        run([sys.executable, "-m", "demos.run_demos"], cwd=root, stdout=handle)
    traces = json.loads(output.read_text(encoding="utf-8"))
    expected = {
        "public_0149": ("buying", "B07CBYYHTL", 2, 2),
        "public_0006": ("browsing", "B071F2Z7JG", 2, 1),
        "public_0072": ("intent_override", "B09JG4V9ZR", 3, 1),
        "public_0131": ("boundary", "B07PQQQ8ZL", 2, 2),
    }
    indexed = {trace.get("sample_id"): trace for trace in traces}
    if set(indexed) != set(expected):
        raise RuntimeError(f"unexpected demo traces: {sorted(indexed)}")
    for sample_id, (scenario, target, final_turn, final_rank) in expected.items():
        trace = indexed[sample_id]
        turns = trace.get("turns") or []
        actual = (
            trace.get("scenario"), trace.get("target"),
            turns[-1].get("turn") if turns else None,
            turns[-1].get("verified_target_rank") if turns else None,
        )
        wanted = (scenario, target, final_turn, final_rank)
        if actual != wanted:
            raise RuntimeError(f"trace claim changed for {sample_id}: {actual} != {wanted}")
    boundary_turns = indexed["public_0131"]["turns"]
    if boundary_turns[0].get("ask_attribute") != "other" or boundary_turns[1].get("ask_attribute") == "other":
        raise RuntimeError("boundary trace repeated a no-preference clarification")
    override_text = indexed["public_0072"]["turns"][-1].get("customer", "").lower()
    if "ignore my earlier preference" not in override_text:
        raise RuntimeError("override trace no longer contains explicit revocation")


def build_segment(
    segment: Segment,
    index: int,
    total: int,
    work: Path,
    renderer: Path,
    voice: str,
    rate: int,
) -> Path:
    prefix = f"{index:02d}"
    title_path = work / f"{prefix}-title.txt"
    body_path = work / f"{prefix}-body.txt"
    narration_path = work / f"{prefix}-narration.txt"
    audio_path = work / f"{prefix}.aiff"
    slide_path = work / f"{prefix}.png"
    video_path = work / f"{prefix}.mp4"
    title_path.write_text(segment.title + "\n", encoding="utf-8")
    body_path.write_text(segment.body + "\n", encoding="utf-8")
    narration_path.write_text(segment.narration + "\n", encoding="utf-8")
    run(["say", "-v", voice, "-r", str(rate), "-f", str(narration_path), "-o", str(audio_path)])
    run([
        str(renderer), str(slide_path), str(title_path), str(body_path),
        segment.accent, str(index), str(total),
    ])
    slide_duration = duration(audio_path) + 1.0
    fade_out = max(0.5, slide_duration - 0.45)
    filters = (
        f"fade=t=in:st=0:d=0.35,fade=t=out:st={fade_out:.3f}:d=0.4"
    )
    run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-loop", "1", "-framerate", "30", "-i", str(slide_path),
        "-i", str(audio_path),
        "-vf", filters,
        "-af", "afade=t=in:st=0:d=0.2,apad",
        "-t", f"{slide_duration:.3f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-tune", "stillimage",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart", str(video_path),
    ])
    return video_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voice", default="Samantha")
    parser.add_argument("--rate", type=int, default=175)
    parser.add_argument("--output", default="output/demo/shopping-copilot-techjam-2026.mp4")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output_root = (root / "output").resolve()
    final_path = (root / args.output).resolve()
    try:
        final_path.relative_to(output_root)
    except ValueError as error:
        raise SystemExit("--output must resolve inside the repository output/ directory") from error
    if final_path.suffix.lower() != ".mp4":
        raise SystemExit("--output must name an .mp4 file")
    work = output_root / ".demo-build"
    if work == final_path or work in final_path.parents:
        raise SystemExit("--output cannot be inside output/.demo-build")
    if work.exists():
        shutil.rmtree(work)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True)
    verify_traces(root, work / "verified-traces.json")
    renderer = prepare_renderer(work)
    videos = [
        build_segment(segment, index, len(SEGMENTS), work, renderer, args.voice, args.rate)
        for index, segment in enumerate(SEGMENTS, 1)
    ]
    concat = work / "concat.txt"
    concat.write_text("".join(f"file '{path.resolve()}'\n" for path in videos), encoding="utf-8")
    run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat),
        "-c", "copy", "-movflags", "+faststart", str(final_path),
    ])
    thumbnail = final_path.with_suffix(".png")
    run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", "1", "-i", str(final_path), "-frames:v", "1", str(thumbnail),
    ])
    final_duration = duration(final_path)
    if final_duration > 180:
        raise RuntimeError(f"video exceeds the three-minute limit: {final_duration:.3f}s")
    print(json.dumps({
        "video": str(final_path),
        "thumbnail": str(thumbnail),
        "duration_seconds": round(final_duration, 3),
        "size_bytes": final_path.stat().st_size,
    }, indent=2))


if __name__ == "__main__":
    main()
