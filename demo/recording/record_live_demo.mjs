#!/usr/bin/env node

import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { once } from "node:events";
import { createReadStream } from "node:fs";
import { promises as fs } from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import { performance } from "node:perf_hooks";
import process from "node:process";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";


const require = createRequire(import.meta.url);
const playwrightPackage = require("playwright/package.json");
const SCRIPT_PATH = fileURLToPath(import.meta.url);
const RECORDING_DIR = path.dirname(SCRIPT_PATH);

const WIDTH = 1920;
const HEIGHT = 1080;
const FPS = 30;
const JPEG_QUALITY = 92;
const CRF = 18;
const TARGET_DURATION_SECONDS = 166;
const MIN_DURATION_SECONDS = 160;
const MAX_DURATION_SECONDS = 169.25;
const HEALTH_TIMEOUT_MS = 120_000;
const UI_TIMEOUT_MS = 20_000;
const BROWSE_ASIN = "B071F2Z7JG";
const BROWSE_TITLE = "Pro Club Men's Heavyweight Mesh Basketball Shorts";
const BROWSE_REFINEMENT = "For that, what matters is: polyester; 100% Polyester.";
const OVERRIDE_ASIN = "B09JG4V9ZR";
const OVERRIDE_TITLE = "Facitisu Womens Winter Warm Jacket Long Down Faux Fur Hooded Quilted Sherpa Lined Coat";
const OVERRIDE_REFINEMENT = "For that, what matters is: Faux Fur; Drawstring closure.";
const OVERRIDE_VALUE = "Faux Fur";
const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "[::1]", "::1"]);


class RecordingError extends Error {
  constructor(message) {
    super(message);
    this.name = "RecordingError";
  }
}


function usage() {
  return [
    "Usage:",
    "  node demo/recording/record_live_demo.mjs \\",
    "    --base-url http://127.0.0.1:PORT \\",
    "    --output /absolute/path/live-demo.mp4 \\",
    "    --manifest /absolute/path/live-demo.json",
    "",
    "The service must already be ready, loopback-only, and started without OPENAI_API_KEY.",
  ].join("\n");
}


function parseArguments(argv) {
  if (argv.includes("--help") || argv.includes("-h")) {
    process.stdout.write(`${usage()}\n`);
    return null;
  }
  const values = new Map();
  for (let index = 0; index < argv.length; index += 1) {
    const key = argv[index];
    if (!new Set(["--base-url", "--output", "--manifest"]).has(key)) {
      throw new RecordingError(`unknown argument: ${key}\n${usage()}`);
    }
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) {
      throw new RecordingError(`missing value for ${key}\n${usage()}`);
    }
    if (values.has(key)) throw new RecordingError(`argument supplied more than once: ${key}`);
    values.set(key, value);
    index += 1;
  }
  for (const key of ["--base-url", "--output", "--manifest"]) {
    if (!values.has(key)) throw new RecordingError(`missing required argument: ${key}\n${usage()}`);
  }

  let baseUrl;
  try {
    baseUrl = new URL(values.get("--base-url"));
  } catch {
    throw new RecordingError("--base-url must be a valid URL");
  }
  if (!new Set(["http:", "https:"]).has(baseUrl.protocol) || !LOOPBACK_HOSTS.has(baseUrl.hostname)) {
    throw new RecordingError("--base-url must use http(s) on 127.0.0.1, localhost, or ::1");
  }
  if (baseUrl.username || baseUrl.password) {
    throw new RecordingError("--base-url must not contain credentials");
  }
  baseUrl.pathname = "/";
  baseUrl.search = "";
  baseUrl.hash = "";

  const output = path.resolve(values.get("--output"));
  const manifest = path.resolve(values.get("--manifest"));
  if (!path.isAbsolute(values.get("--output")) || path.extname(output).toLowerCase() !== ".mp4") {
    throw new RecordingError("--output must be an absolute .mp4 path");
  }
  if (!path.isAbsolute(values.get("--manifest")) || path.extname(manifest).toLowerCase() !== ".json") {
    throw new RecordingError("--manifest must be an absolute .json path");
  }
  if (output === manifest) throw new RecordingError("--output and --manifest must be different paths");
  return { baseUrl, output, manifest };
}


function check(condition, message) {
  if (!condition) throw new RecordingError(message);
}


function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}


async function withTimeout(promise, timeoutMs, message) {
  let timer;
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new RecordingError(message)), timeoutMs);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}


async function waitForAsync(label, callback, timeoutMs = UI_TIMEOUT_MS, intervalMs = 100) {
  const deadline = performance.now() + timeoutMs;
  let lastError;
  while (performance.now() < deadline) {
    try {
      const result = await callback();
      if (result) return result;
    } catch (error) {
      lastError = error;
    }
    await sleep(intervalMs);
  }
  const suffix = lastError instanceof Error ? ` Last error: ${lastError.message}` : "";
  throw new RecordingError(`timed out waiting for ${label}.${suffix}`);
}


function commandOutput(command, args) {
  const result = spawnSync(command, args, { encoding: "utf8" });
  if (result.error) throw new RecordingError(`required command is unavailable: ${command}`);
  if (result.status !== 0) {
    const detail = (result.stderr || result.stdout || "").trim();
    throw new RecordingError(`${command} failed${detail ? `: ${detail.slice(-1000)}` : ""}`);
  }
  return result.stdout.trim();
}


async function sha256File(filename) {
  const digest = createHash("sha256");
  for await (const chunk of createReadStream(filename)) digest.update(chunk);
  return digest.digest("hex");
}


function safeExternalUrl(rawUrl) {
  try {
    const parsed = new URL(rawUrl);
    return `${parsed.protocol}//${parsed.host}${parsed.pathname}`;
  } catch {
    return "unparseable-url";
  }
}


function isAllowedOrigin(rawUrl, allowedOrigin) {
  try {
    const parsed = new URL(rawUrl);
    return new Set(["http:", "https:"]).has(parsed.protocol) && parsed.origin === allowedOrigin;
  } catch {
    return false;
  }
}


function sha256Value(value) {
  return createHash("sha256").update(value).digest("hex");
}


async function captureApiExchange(response, sequence) {
  const request = response.request();
  const parsedUrl = new URL(response.url());
  const messageMatch = parsedUrl.pathname.match(/^\/api\/sessions\/([0-9a-f]{32})\/messages$/);
  const sanitizedPath = messageMatch ? "/api/sessions/{session_id}/messages" : parsedUrl.pathname;
  const requestText = request.postData() ?? "";
  const responseBuffer = await response.body();
  let requestPayload = null;
  let responsePayload = null;
  try { requestPayload = requestText ? JSON.parse(requestText) : null; } catch { /* Hash remains authoritative. */ }
  try { responsePayload = JSON.parse(responseBuffer.toString("utf8")); } catch { /* Hash remains authoritative. */ }
  const recommendations = responsePayload?.agent_response?.recommendations;
  const routeProbability = responsePayload?.expert_state?.route_probabilities?.override;
  return {
    sequence,
    method: request.method(),
    path: sanitizedPath,
    status: response.status(),
    request_sha256: sha256Value(requestText),
    response_sha256: sha256Value(responseBuffer),
    request_session_id_sha256: messageMatch ? sha256Value(messageMatch[1]) : null,
    request: requestPayload && typeof requestPayload === "object" ? {
      mode: requestPayload.mode,
      marketplace: requestPayload.marketplace,
      expected_turn: requestPayload.expected_turn,
      message: requestPayload.message,
    } : null,
    response: responsePayload && typeof responsePayload === "object" ? {
      session_id_sha256: typeof responsePayload.session_id === "string" ? sha256Value(responsePayload.session_id) : null,
      turn: responsePayload.turn,
      mode: responsePayload.mode,
      recommendation_asins: Array.isArray(recommendations) ? recommendations : [],
      intent_generation: responsePayload.expert_state?.intent_generation,
      override_probability: typeof routeProbability === "number" ? routeProbability : null,
    } : null,
  };
}


function attachApiEvidence(page, allowedOrigin) {
  const exchanges = [];
  const errors = [];
  const pending = new Set();
  let sequence = 0;

  const onResponse = (response) => {
    let parsed;
    try {
      parsed = new URL(response.url());
    } catch {
      return;
    }
    if (parsed.origin !== allowedOrigin || response.request().method() !== "POST" || !parsed.pathname.startsWith("/api/")) {
      return;
    }
    sequence += 1;
    let task;
    task = captureApiExchange(response, sequence)
      .then((exchange) => { exchanges.push(exchange); })
      .catch((error) => {
        errors.push(error instanceof Error ? error.message : String(error));
      })
      .finally(() => { pending.delete(task); });
    pending.add(task);
  };
  page.on("response", onResponse);

  return {
    exchanges,
    errors,
    async settle() {
      while (pending.size > 0) await Promise.allSettled([...pending]);
      exchanges.sort((left, right) => left.sequence - right.sequence);
      check(errors.length === 0, `could not capture local API evidence: ${errors.join(" | ")}`);
    },
    detach() {
      page.off("response", onResponse);
    },
  };
}


function successfulSessionCreations(exchanges) {
  return exchanges.filter((exchange) => (
    exchange.method === "POST"
      && exchange.path === "/api/sessions"
      && exchange.status === 201
      && typeof exchange.response?.session_id_sha256 === "string"
  ));
}


function validateHealth(payload) {
  check(payload && typeof payload === "object" && !Array.isArray(payload), "health response must be a JSON object");
  check(payload.status === "ready", `health status must be ready; received ${String(payload.status)}`);
  check(payload.catalog_count === 50_000, `health catalog_count must be 50000; received ${String(payload.catalog_count)}`);
  check(payload.max_turns === 10, `health max_turns must be 10; received ${String(payload.max_turns)}`);
  check(payload.agent_contract === "reset/respond-v1", `unexpected Agent contract: ${String(payload.agent_contract)}`);
  check(payload.hybrid_available === false, "refusing to record: Hybrid is available; restart a dedicated server without OPENAI_API_KEY");
  return payload;
}


async function waitForHealth(baseUrl) {
  const healthUrl = new URL("/api/health", baseUrl);
  const deadline = performance.now() + HEALTH_TIMEOUT_MS;
  let lastError;
  while (performance.now() < deadline) {
    try {
      const response = await fetch(healthUrl, {
        headers: { Accept: "application/json" },
        cache: "no-store",
        signal: AbortSignal.timeout(4_000),
      });
      if (response.ok) {
        const payload = await response.json();
        if (payload?.status === "ready") return validateHealth(payload);
        if (payload?.status === "failed") throw new RecordingError("the local catalog index reported a startup failure");
      } else {
        lastError = new Error(`HTTP ${response.status}`);
      }
    } catch (error) {
      if (error instanceof RecordingError) throw error;
      lastError = error;
    }
    await sleep(750);
  }
  const detail = lastError instanceof Error ? ` Last error: ${lastError.message}` : "";
  throw new RecordingError(`the local service did not become ready within ${HEALTH_TIMEOUT_MS / 1000} seconds.${detail}`);
}


function jpegDimensions(buffer) {
  if (buffer.length < 4 || buffer[0] !== 0xff || buffer[1] !== 0xd8) return null;
  let offset = 2;
  while (offset + 8 < buffer.length) {
    if (buffer[offset] !== 0xff) {
      offset += 1;
      continue;
    }
    const marker = buffer[offset + 1];
    offset += 2;
    if (marker === 0xd8 || marker === 0xd9) continue;
    if (offset + 2 > buffer.length) break;
    const length = buffer.readUInt16BE(offset);
    const isStartOfFrame = new Set([0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf]).has(marker);
    if (isStartOfFrame && offset + 7 < buffer.length) {
      return { height: buffer.readUInt16BE(offset + 3), width: buffer.readUInt16BE(offset + 5) };
    }
    if (length < 2) break;
    offset += length;
  }
  return null;
}


async function writeWithBackpressure(stream, buffer, ffmpegExit) {
  if (stream.destroyed || !stream.writable) throw new RecordingError("FFmpeg input closed while recording");
  if (stream.write(buffer)) return;
  const outcome = await Promise.race([
    once(stream, "drain").then(() => ({ kind: "drain" })),
    ffmpegExit.then((result) => ({ kind: "exit", result })),
  ]);
  if (outcome.kind === "exit") {
    const detail = outcome.result?.error?.message
      ?? `code ${String(outcome.result?.code)} signal ${String(outcome.result?.signal)}`;
    throw new RecordingError(`FFmpeg exited while its input was backpressured: ${detail}`);
  }
}


class ScreencastRecorder {
  constructor({ cdp, output, ffmpeg }) {
    this.cdp = cdp;
    this.output = output;
    this.ffmpegCommand = ffmpeg;
    this.latestFrame = null;
    this.firstFrameMetadata = null;
    this.firstFrameDimensions = null;
    this.firstFrameResolve = null;
    this.firstFramePromise = new Promise((resolve) => { this.firstFrameResolve = resolve; });
    this.framesWritten = 0;
    this.sourceFramesReceived = 0;
    this.changedSourceFrames = 0;
    this.acksStarted = 0;
    this.acksCompleted = 0;
    this.pendingAcks = new Set();
    this.latestFrameSha256 = null;
    this.lastSourceFrameAtMs = null;
    this.changeCheckpoints = [];
    this.running = false;
    this.startedAtMs = null;
    this.pumpPromise = null;
    this.ffmpeg = null;
    this.ffmpegExit = null;
    this.ffmpegStderr = "";
    this.streamError = null;
    this.cdpError = null;
    this.onFrame = (event) => {
      const frame = Buffer.from(event.data, "base64");
      this.sourceFramesReceived += 1;
      if (!this.latestFrame || !frame.equals(this.latestFrame)) this.changedSourceFrames += 1;
      this.latestFrame = frame;
      this.latestFrameSha256 = sha256Value(frame);
      this.lastSourceFrameAtMs = performance.now();
      if (this.sourceFramesReceived === 1) {
        this.firstFrameMetadata = event.metadata ?? null;
        this.firstFrameDimensions = jpegDimensions(frame);
        this.firstFrameResolve();
      }
      this.acksStarted += 1;
      let acknowledgment;
      try {
        acknowledgment = this.cdp.send("Page.screencastFrameAck", { sessionId: event.sessionId });
      } catch (error) {
        this.cdpError = error;
        return;
      }
      let tracked;
      tracked = acknowledgment
        .then(() => { this.acksCompleted += 1; })
        .catch((error) => { this.cdpError = error; })
        .finally(() => { this.pendingAcks.delete(tracked); });
      this.pendingAcks.add(tracked);
    };
  }

  elapsedSeconds() {
    return this.startedAtMs === null ? 0 : (performance.now() - this.startedAtMs) / 1000;
  }

  assertHealthy() {
    if (this.streamError) throw new RecordingError(`FFmpeg input failed: ${this.streamError.message}`);
    if (this.cdpError) throw new RecordingError(`browser screencast failed: ${this.cdpError.message}`);
    if (this.ffmpegExit?.settled && this.ffmpegExit.result.code !== 0) {
      throw new RecordingError(`FFmpeg exited during recording: ${this.ffmpegStderr.slice(-1200)}`);
    }
  }

  sourceCheckpoint() {
    this.assertHealthy();
    check(this.latestFrameSha256, "cannot create a source-frame checkpoint before the first browser frame");
    return {
      source_frames_received: this.sourceFramesReceived,
      changed_source_frames: this.changedSourceFrames,
      latest_frame_sha256: this.latestFrameSha256,
    };
  }

  async requireChangedFrameAfter(checkpoint, label, timeoutMs = 6_000) {
    await waitForAsync(`${label} in the captured browser stream`, async () => {
      this.assertHealthy();
      return this.sourceFramesReceived > checkpoint.source_frames_received
        && this.changedSourceFrames > checkpoint.changed_source_frames;
    }, timeoutMs, 40);
    const evidence = {
      label,
      source_frames_received: this.sourceFramesReceived,
      changed_source_frames: this.changedSourceFrames,
      latest_frame_sha256: this.latestFrameSha256,
    };
    this.changeCheckpoints.push(evidence);
    return evidence;
  }

  async settleAcks(timeoutMs = 5_000) {
    const deadline = performance.now() + timeoutMs;
    while (this.pendingAcks.size > 0) {
      const remainingMs = deadline - performance.now();
      check(remainingMs > 0, `CDP frame acknowledgments did not settle within ${timeoutMs} ms`);
      await withTimeout(
        Promise.allSettled([...this.pendingAcks]),
        remainingMs,
        `CDP frame acknowledgments did not settle within ${timeoutMs} ms`,
      );
    }
    this.assertHealthy();
  }

  async start() {
    check(!this.running, "recorder was already started");
    const args = [
      "-hide_banner", "-loglevel", "error", "-y",
      "-f", "image2pipe", "-framerate", String(FPS), "-vcodec", "mjpeg", "-i", "pipe:0",
      "-an",
      "-vf", `scale=${WIDTH}:${HEIGHT}:flags=lanczos:in_range=pc:out_range=tv,setsar=1,format=yuv420p`,
      "-r", String(FPS), "-c:v", "libx264", "-preset", "medium", "-crf", String(CRF),
      "-profile:v", "high", "-level:v", "4.1", "-pix_fmt", "yuv420p", "-color_range", "tv",
      "-movflags", "+faststart",
      this.output,
    ];
    this.ffmpeg = spawn(this.ffmpegCommand, args, { stdio: ["pipe", "ignore", "pipe"] });
    this.ffmpeg.stdin.on("error", (error) => { this.streamError = error; });
    this.ffmpeg.stderr.on("data", (chunk) => {
      this.ffmpegStderr = `${this.ffmpegStderr}${chunk.toString("utf8")}`.slice(-16_000);
    });
    const exitState = { settled: false, result: null };
    exitState.promise = new Promise((resolve) => {
      this.ffmpeg.once("error", (error) => {
        exitState.settled = true;
        exitState.result = { code: null, signal: null, error };
        resolve(exitState.result);
      });
      this.ffmpeg.once("close", (code, signal) => {
        exitState.settled = true;
        exitState.result = { code, signal, error: null };
        resolve(exitState.result);
      });
    });
    this.ffmpegExit = exitState;

    this.cdp.on("Page.screencastFrame", this.onFrame);
    await this.cdp.send("Page.enable");
    await this.cdp.send("Page.startScreencast", {
      format: "jpeg",
      quality: JPEG_QUALITY,
      maxWidth: WIDTH,
      maxHeight: HEIGHT,
      everyNthFrame: 1,
    });
    await Promise.race([
      this.firstFramePromise,
      sleep(8_000).then(() => { throw new RecordingError("Chromium did not produce an initial screencast frame"); }),
    ]);
    await this.settleAcks(3_000);
    check(
      this.firstFrameDimensions?.width === WIDTH && this.firstFrameDimensions?.height === HEIGHT,
      `initial browser frame must be ${WIDTH}x${HEIGHT}; received ${JSON.stringify(this.firstFrameDimensions)}`,
    );
    this.startedAtMs = performance.now();
    this.running = true;
    this.pumpPromise = this.pump();
  }

  async writeExpectedFrames() {
    check(this.latestFrame, "no browser frame is available for encoding");
    const expectedFrames = Math.max(1, Math.floor(this.elapsedSeconds() * FPS) + 1);
    while (this.framesWritten < expectedFrames) {
      await writeWithBackpressure(this.ffmpeg.stdin, this.latestFrame, this.ffmpegExit.promise);
      this.framesWritten += 1;
    }
  }

  async pump() {
    while (this.running) {
      this.assertHealthy();
      await this.writeExpectedFrames();
      await sleep(4);
    }
    await this.writeExpectedFrames();
  }

  async stop() {
    if (!this.ffmpeg) throw new RecordingError("recorder was not started");
    this.running = false;
    await this.pumpPromise;
    await this.cdp.send("Page.stopScreencast").catch((error) => { this.cdpError ??= error; });
    this.cdp.off("Page.screencastFrame", this.onFrame);
    await this.settleAcks();
    this.ffmpeg.stdin.end();
    const result = await this.ffmpegExit.promise;
    if (result.error) throw new RecordingError(`could not start FFmpeg: ${result.error.message}`);
    if (result.code !== 0) {
      throw new RecordingError(`FFmpeg failed with code ${String(result.code)}${this.ffmpegStderr ? `: ${this.ffmpegStderr.slice(-1200)}` : ""}`);
    }
    this.assertHealthy();
    check(this.sourceFramesReceived >= 24, `captured only ${this.sourceFramesReceived} source frames`);
    check(this.changedSourceFrames >= 16, `captured only ${this.changedSourceFrames} changed source frames`);
    check(this.changeCheckpoints.length >= 9, "the storyboard did not prove source-frame changes across its major scenes");
    check(this.acksStarted === this.sourceFramesReceived, "not every source frame started a CDP acknowledgment");
    check(this.acksCompleted === this.sourceFramesReceived, "not every source frame completed its CDP acknowledgment");
    const sourceFrameAgeSeconds = this.lastSourceFrameAtMs === null
      ? Number.POSITIVE_INFINITY
      : (performance.now() - this.lastSourceFrameAtMs) / 1000;
    check(sourceFrameAgeSeconds <= 35, `the browser stream was stale for ${sourceFrameAgeSeconds.toFixed(3)} seconds at stop`);
    return {
      elapsed_seconds: Number(this.elapsedSeconds().toFixed(3)),
      frames_written: this.framesWritten,
      source_frames_received: this.sourceFramesReceived,
      changed_source_frames: this.changedSourceFrames,
      acknowledgments_started: this.acksStarted,
      acknowledgments_completed: this.acksCompleted,
      source_frame_age_at_stop_seconds: Number(sourceFrameAgeSeconds.toFixed(3)),
      change_checkpoints: this.changeCheckpoints,
      source_frame: this.firstFrameDimensions,
      first_frame_metadata: this.firstFrameMetadata,
    };
  }

  async abort() {
    this.running = false;
    await this.cdp.send("Page.stopScreencast").catch(() => undefined);
    this.cdp.off("Page.screencastFrame", this.onFrame);
    if (this.ffmpeg) {
      this.ffmpeg.stdin.destroy();
      if (!this.ffmpeg.killed) this.ffmpeg.kill("SIGTERM");
    }
    await this.pumpPromise?.catch(() => undefined);
    await this.ffmpegExit?.promise.catch(() => undefined);
  }
}


async function hold(recorder, milliseconds, interrupted) {
  const deadline = performance.now() + milliseconds;
  while (performance.now() < deadline) {
    if (interrupted.value) throw new RecordingError(`recording interrupted by ${interrupted.value}`);
    recorder.assertHealthy();
    await sleep(Math.min(250, Math.max(1, deadline - performance.now())));
  }
}


async function installVisibleCursor(page) {
  await page.evaluate(() => {
    const cursor = document.createElement("div");
    const ring = document.createElement("div");
    cursor.id = "shopping-copilot-demo-cursor";
    ring.id = "shopping-copilot-demo-click-ring";
    cursor.setAttribute("aria-hidden", "true");
    ring.setAttribute("aria-hidden", "true");
    Object.assign(cursor.style, {
      position: "fixed", left: "1840px", top: "1000px", width: "20px", height: "20px",
      borderRadius: "50%", background: "#ff6b4b", border: "3px solid #fff",
      boxShadow: "0 2px 9px rgba(0,0,0,.55)", transform: "translate(-50%, -50%)",
      pointerEvents: "none", zIndex: "2147483647",
    });
    Object.assign(ring.style, {
      position: "fixed", left: "1840px", top: "1000px", width: "42px", height: "42px",
      borderRadius: "50%", border: "4px solid rgba(255,107,75,.9)",
      boxShadow: "0 0 0 3px rgba(255,255,255,.82)", transform: "translate(-50%, -50%) scale(.55)",
      opacity: "0", pointerEvents: "none", zIndex: "2147483646",
    });
    document.body.append(cursor, ring);
    let ringTimer = 0;
    document.addEventListener("mousemove", (event) => {
      cursor.style.left = `${event.clientX}px`;
      cursor.style.top = `${event.clientY}px`;
      ring.style.left = `${event.clientX}px`;
      ring.style.top = `${event.clientY}px`;
    }, true);
    document.addEventListener("mousedown", () => {
      window.clearTimeout(ringTimer);
      ring.style.opacity = "1";
      ring.style.transform = "translate(-50%, -50%) scale(1)";
    }, true);
    document.addEventListener("mouseup", () => {
      ringTimer = window.setTimeout(() => {
        ring.style.opacity = "0";
        ring.style.transform = "translate(-50%, -50%) scale(.55)";
      }, 420);
    }, true);
  });
  await page.mouse.move(1840, 1000);
}


function createPointer(page, recorder, interrupted) {
  let position = { x: 1840, y: 1000 };

  async function moveTo(locator, durationMs = 780) {
    await locator.waitFor({ state: "visible", timeout: UI_TIMEOUT_MS });
    await locator.scrollIntoViewIfNeeded();
    const box = await locator.boundingBox();
    if (!box || box.width <= 0 || box.height <= 0) throw new RecordingError("target control has no clickable browser bounds");
    const target = {
      x: Math.max(8, Math.min(WIDTH - 8, box.x + box.width / 2)),
      y: Math.max(8, Math.min(HEIGHT - 8, box.y + box.height / 2)),
    };
    const steps = Math.max(12, Math.round(durationMs / 28));
    const start = position;
    for (let step = 1; step <= steps; step += 1) {
      const progress = step / steps;
      const eased = progress < 0.5 ? 2 * progress * progress : 1 - ((-2 * progress + 2) ** 2) / 2;
      const x = start.x + (target.x - start.x) * eased;
      const y = start.y + (target.y - start.y) * eased;
      await page.mouse.move(x, y);
      await hold(recorder, durationMs / steps, interrupted);
    }
    position = target;
  }

  async function click(locator, durationMs = 780) {
    await moveTo(locator, durationMs);
    await hold(recorder, 220, interrupted);
    await page.mouse.down();
    await hold(recorder, 110, interrupted);
    await page.mouse.up();
    await hold(recorder, 520, interrupted);
  }

  return { moveTo, click };
}


async function visiblyType(locator, text, pointer, recorder, interrupted) {
  await pointer.click(locator, 650);
  await locator.fill("");
  await locator.pressSequentially(text, { delay: 38 });
  await hold(recorder, 850, interrupted);
}


async function waitForTurn(page, turn) {
  await page.locator(".turn-badge", { hasText: `Turn ${turn} / 10` }).waitFor({ state: "visible", timeout: UI_TIMEOUT_MS });
  await waitForAsync(`${turn === 1 ? "first" : `turn ${turn}`} recommendation set`, async () => (
    await page.locator('[data-testid="product-card"]').count()
  ) === 10);
}


async function assertRankOne(page, asin, title) {
  const cards = page.locator('[data-testid="product-card"]');
  await waitForAsync(`${asin} at rank one`, async () => {
    if (await cards.count() !== 10) return false;
    const first = cards.first();
    const text = (await first.textContent()) ?? "";
    const rank = (await first.locator(".rank").textContent())?.trim();
    const href = await first.locator('a[href*="/s?k="]').getAttribute("href");
    return text.includes(title) && rank === "#1" && Boolean(href?.includes(asin));
  });
  const links = await cards.locator('a[href*="/s?k="]').evaluateAll((elements) => elements.map((element) => element.getAttribute("href") ?? ""));
  const asins = links.map((href) => new URL(href).searchParams.get("k"));
  check(asins.every((value) => typeof value === "string" && value.length > 0), "a recommendation was missing its catalog ASIN verification link");
  check(new Set(asins).size === 10, "the visible recommendation set contains duplicate ASINs");
  return { asin, rank: 1, title, recommendation_count: 10, unique_recommendations: true };
}


function probeVideo(ffprobe, filename) {
  const raw = commandOutput(ffprobe, [
    "-v", "error",
    "-show_entries", "format=duration,size:stream=codec_type,codec_name,width,height,r_frame_rate,pix_fmt",
    "-of", "json", filename,
  ]);
  let payload;
  try {
    payload = JSON.parse(raw);
  } catch {
    throw new RecordingError("ffprobe returned invalid JSON for the recorded MP4");
  }
  const streams = Array.isArray(payload.streams) ? payload.streams : [];
  const video = streams.find((stream) => stream.codec_type === "video");
  const duration = Number(payload.format?.duration);
  const size = Number(payload.format?.size);
  check(video?.codec_name === "h264", `recorded video codec must be H.264; received ${String(video?.codec_name)}`);
  check(video.width === WIDTH && video.height === HEIGHT, `recorded video must be ${WIDTH}x${HEIGHT}`);
  check(video.r_frame_rate === `${FPS}/1`, `recorded video must be ${FPS} fps; received ${String(video.r_frame_rate)}`);
  check(video.pix_fmt === "yuv420p", `recorded video must use yuv420p; received ${String(video.pix_fmt)}`);
  check(Number.isFinite(duration) && duration >= MIN_DURATION_SECONDS && duration <= MAX_DURATION_SECONDS,
    `recorded duration must be ${MIN_DURATION_SECONDS}-${MAX_DURATION_SECONDS} seconds; received ${String(duration)}`);
  check(Number.isFinite(size) && size > 0, "recorded MP4 is empty");
  return {
    duration_seconds: Number(duration.toFixed(3)),
    size_bytes: size,
    codec: video.codec_name,
    width: video.width,
    height: video.height,
    fps: video.r_frame_rate,
    pixel_format: video.pix_fmt,
  };
}


async function runStoryboard({ page, recorder, events, assertions, interrupted, apiEvidence, initialSessionExchange }) {
  const pointer = createPointer(page, recorder, interrupted);
  const event = (key, details = undefined) => {
    const entry = { key, at_seconds: Number(recorder.elapsedSeconds().toFixed(3)) };
    if (details !== undefined) entry.details = details;
    events.push(entry);
  };

  event("capture_started");
  event("opening_ready", { mode: "offline", saved_products: 0 });
  await hold(recorder, 10_000, interrupted);

  const exploreStarter = page.locator(".starter-grid").getByRole("button", { name: /Help me explore/i });
  event("browse_started", { prompt: "I'm looking for Basketball Men, but I'm still exploring." });
  let sourceCheckpoint = recorder.sourceCheckpoint();
  await pointer.click(exploreStarter);
  await waitForTurn(page, 1);
  await recorder.requireChangedFrameAfter(sourceCheckpoint, "browsing turn one");
  event("browse_turn_1_complete", { turn: 1, recommendations: 10 });
  await hold(recorder, 12_000, interrupted);

  const composer = page.getByLabel("Describe what you are shopping for");
  sourceCheckpoint = recorder.sourceCheckpoint();
  await visiblyType(composer, BROWSE_REFINEMENT, pointer, recorder, interrupted);
  event("browse_refinement_submitted", { message: BROWSE_REFINEMENT });
  await page.keyboard.press("Enter");
  await waitForTurn(page, 2);
  assertions.browse_rank_one = await assertRankOne(page, BROWSE_ASIN, BROWSE_TITLE);
  await recorder.requireChangedFrameAfter(sourceCheckpoint, "browsing refinement and rank-one result");
  event("browse_rank_1_verified", assertions.browse_rank_one);
  await hold(recorder, 14_000, interrupted);

  const firstCard = page.locator('[data-testid="product-card"]').first();
  const openProduct = firstCard.getByRole("button", { name: `Open details for ${BROWSE_TITLE}` }).first();
  sourceCheckpoint = recorder.sourceCheckpoint();
  await pointer.click(openProduct);
  const detailDialog = page.getByRole("dialog", { name: "Product details" });
  await detailDialog.waitFor({ state: "visible", timeout: UI_TIMEOUT_MS });
  check((await detailDialog.textContent())?.includes(BROWSE_TITLE), "product detail did not show the rank-one browsing product");
  check((await detailDialog.textContent())?.includes("Illustrative category art—not a product photo"), "product detail lost its category-art disclosure");
  await recorder.requireChangedFrameAfter(sourceCheckpoint, "rank-one product detail");
  assertions.product_detail = { asin: BROWSE_ASIN, title: BROWSE_TITLE, disclosure_visible: true };
  event("product_detail_opened", assertions.product_detail);
  await hold(recorder, 9_000, interrupted);
  const detailBox = await detailDialog.boundingBox();
  if (detailBox) {
    await page.mouse.move(detailBox.x + detailBox.width * 0.72, detailBox.y + detailBox.height * 0.72);
    await page.mouse.wheel(0, 520);
    await hold(recorder, 4_500, interrupted);
    await page.mouse.wheel(0, -520);
    await hold(recorder, 1_000, interrupted);
  }
  await pointer.click(detailDialog.getByRole("button", { name: "Close product details" }), 600);
  await detailDialog.waitFor({ state: "hidden", timeout: UI_TIMEOUT_MS });

  sourceCheckpoint = recorder.sourceCheckpoint();
  await pointer.click(page.getByRole("button", { name: "How it decided" }), 720);
  const expertDialog = page.getByRole("dialog", { name: "How it decided" });
  await expertDialog.waitFor({ state: "visible", timeout: UI_TIMEOUT_MS });
  const diagnostic = expertDialog.locator(".diagnostic-hero");
  check((await diagnostic.textContent())?.includes("2 / 10"), "Expert mode did not show browsing turn 2");
  check((await diagnostic.textContent())?.includes("v1"), "Expert mode did not show intent version v1 before override");
  await recorder.requireChangedFrameAfter(sourceCheckpoint, "browsing Expert v1");
  assertions.expert_v1 = { turn: 2, intent_version: "v1" };
  event("expert_v1_verified", assertions.expert_v1);
  await hold(recorder, 14_000, interrupted);
  await pointer.click(expertDialog.getByRole("button", { name: "Close expert mode" }), 600);
  await expertDialog.waitFor({ state: "hidden", timeout: UI_TIMEOUT_MS });

  const conversationTools = page.locator(".conversation-tools");
  sourceCheckpoint = recorder.sourceCheckpoint();
  await pointer.click(conversationTools.getByRole("button", { name: "Restart", exact: true }), 720);
  await page.locator(".turn-badge", { hasText: "Turn 0 / 10" }).waitFor({ state: "visible", timeout: UI_TIMEOUT_MS });
  await page.locator(".starter-grid").waitFor({ state: "visible", timeout: UI_TIMEOUT_MS });
  const restartedSessionExchange = await waitForAsync("a distinct API session after Restart", async () => {
    await apiEvidence.settle();
    return successfulSessionCreations(apiEvidence.exchanges).find((exchange) => (
      exchange.sequence > initialSessionExchange.sequence
        && exchange.response.session_id_sha256 !== initialSessionExchange.response.session_id_sha256
    ));
  });
  await recorder.requireChangedFrameAfter(sourceCheckpoint, "fresh session after Restart");
  assertions.restart_session = {
    changed_session_id: true,
    initial_session_id_sha256: initialSessionExchange.response.session_id_sha256,
    restarted_session_id_sha256: restartedSessionExchange.response.session_id_sha256,
    initial_exchange_sequence: initialSessionExchange.sequence,
    restarted_exchange_sequence: restartedSessionExchange.sequence,
  };
  event("restarted", { mode: "offline", turn: 0, changed_session_id: true });
  await hold(recorder, 6_000, interrupted);

  const overrideStarter = page.locator(".starter-grid").getByRole("button", { name: /Change direction/i });
  sourceCheckpoint = recorder.sourceCheckpoint();
  await pointer.click(overrideStarter);
  await waitForTurn(page, 1);
  await recorder.requireChangedFrameAfter(sourceCheckpoint, "override turn one");
  event("override_turn_1_complete", { turn: 1, recommendations: 10 });
  await hold(recorder, 8_000, interrupted);

  sourceCheckpoint = recorder.sourceCheckpoint();
  await visiblyType(page.getByLabel("Describe what you are shopping for"), OVERRIDE_REFINEMENT, pointer, recorder, interrupted);
  await page.keyboard.press("Enter");
  await waitForTurn(page, 2);
  await recorder.requireChangedFrameAfter(sourceCheckpoint, "override turn two constraints");
  event("override_turn_2_complete", { turn: 2, message: OVERRIDE_REFINEMENT, recommendations: 10 });
  await hold(recorder, 12_000, interrupted);

  sourceCheckpoint = recorder.sourceCheckpoint();
  await pointer.click(conversationTools.getByRole("button", { name: "Change direction", exact: true }), 720);
  const overrideInput = page.getByLabel("What should replace your earlier preference?");
  await overrideInput.waitFor({ state: "visible", timeout: UI_TIMEOUT_MS });
  await hold(recorder, 2_000, interrupted);
  await visiblyType(overrideInput, OVERRIDE_VALUE, pointer, recorder, interrupted);
  event("override_change_submitted", { value: OVERRIDE_VALUE });
  await pointer.click(page.getByRole("button", { name: "Apply change", exact: true }), 520);
  await waitForTurn(page, 3);
  assertions.override_rank_one = await assertRankOne(page, OVERRIDE_ASIN, OVERRIDE_TITLE);
  await recorder.requireChangedFrameAfter(sourceCheckpoint, "applied override and rank-one result");
  event("override_rank_1_verified", assertions.override_rank_one);
  await hold(recorder, 12_000, interrupted);

  sourceCheckpoint = recorder.sourceCheckpoint();
  await pointer.click(page.getByRole("button", { name: "How it decided" }), 720);
  await expertDialog.waitFor({ state: "visible", timeout: UI_TIMEOUT_MS });
  const finalDiagnosticText = (await expertDialog.locator(".diagnostic-hero").textContent()) ?? "";
  check(finalDiagnosticText.includes("3 / 10"), "Expert mode did not show override turn 3");
  check(finalDiagnosticText.includes("v2"), "Expert mode did not show intent version v2 after override");
  const overrideRoute = expertDialog.locator(".route-bars > div", { hasText: /override/i });
  await overrideRoute.waitFor({ state: "visible", timeout: UI_TIMEOUT_MS });
  check((await overrideRoute.locator("strong").textContent())?.trim() === "70%", "Expert mode did not show the expected 70% Override route");
  const evidenceText = (await expertDialog.locator(".evidence-groups").textContent()) ?? "";
  check(evidenceText.includes("Rain & Anoraks Anoraks"), "Expert mode did not retain the new category after override");
  check(evidenceText.includes("Faux Fur"), "Expert mode did not retain the Faux Fur requirement");
  check(!evidenceText.includes("Drawstring closure") && !evidenceText.includes("womens"), "Expert mode retained stale non-category override evidence");
  await recorder.requireChangedFrameAfter(sourceCheckpoint, "override Expert v2");
  assertions.expert_v2 = {
    turn: 3,
    intent_version: "v2",
    override_probability: 0.70,
    retained: ["Rain & Anoraks Anoraks", "Faux Fur"],
    revoked: ["womens", "Drawstring closure"],
  };
  event("expert_v2_verified", assertions.expert_v2);
  await hold(recorder, 10_000, interrupted);
  const expertBox = await expertDialog.boundingBox();
  if (expertBox) {
    sourceCheckpoint = recorder.sourceCheckpoint();
    await page.mouse.move(expertBox.x + expertBox.width * 0.72, expertBox.y + expertBox.height * 0.78);
    await page.mouse.wheel(0, 610);
    await hold(recorder, 8_000, interrupted);
    await recorder.requireChangedFrameAfter(sourceCheckpoint, "final Expert evidence view");
  }

  const remainingMs = TARGET_DURATION_SECONDS * 1000 - recorder.elapsedSeconds() * 1000;
  if (remainingMs > 0) await hold(recorder, remainingMs, interrupted);
  check(recorder.elapsedSeconds() <= MAX_DURATION_SECONDS,
    `storyboard exceeded ${MAX_DURATION_SECONDS} seconds before encoding (${recorder.elapsedSeconds().toFixed(3)}s)`);
  event("capture_completed", { target_duration_seconds: TARGET_DURATION_SECONDS });
}


async function main() {
  const options = parseArguments(process.argv.slice(2));
  if (!options) return 0;

  const ffmpeg = process.env.FFMPEG_PATH || "ffmpeg";
  const ffprobe = process.env.FFPROBE_PATH || "ffprobe";
  const ffmpegVersion = commandOutput(ffmpeg, ["-version"]).split("\n")[0];
  const ffprobeVersion = commandOutput(ffprobe, ["-version"]).split("\n")[0];
  const health = await waitForHealth(options.baseUrl);

  await fs.mkdir(path.dirname(options.output), { recursive: true });
  await fs.mkdir(path.dirname(options.manifest), { recursive: true });
  const nonce = `${process.pid}-${Date.now()}`;
  const stagedOutput = path.join(path.dirname(options.output), `.${path.basename(options.output, ".mp4")}.${nonce}.partial.mp4`);
  const stagedManifest = path.join(path.dirname(options.manifest), `.${path.basename(options.manifest, ".json")}.${nonce}.partial.json`);

  let browser;
  let context;
  let recorder;
  let apiEvidence;
  const interrupted = { value: null };
  const onSigint = () => { interrupted.value = "SIGINT"; };
  const onSigterm = () => { interrupted.value = "SIGTERM"; };
  process.once("SIGINT", onSigint);
  process.once("SIGTERM", onSigterm);

  const blockedUrls = [];
  const pageErrors = [];
  const consoleErrors = [];
  const events = [];
  const assertions = {
    health_contract: true,
    offline_mode: false,
  };

  try {
    browser = await chromium.launch({ headless: true });
    context = await browser.newContext({
      viewport: { width: WIDTH, height: HEIGHT },
      screen: { width: WIDTH, height: HEIGHT },
      deviceScaleFactor: 1,
      colorScheme: "light",
      reducedMotion: "reduce",
      locale: "en-US",
      timezoneId: "Asia/Singapore",
      serviceWorkers: "block",
      acceptDownloads: false,
    });
    context.setDefaultTimeout(UI_TIMEOUT_MS);
    await context.route("**/*", async (route) => {
      const requestUrl = route.request().url();
      if (isAllowedOrigin(requestUrl, options.baseUrl.origin)) {
        await route.continue();
      } else {
        blockedUrls.push(safeExternalUrl(requestUrl));
        await route.abort("blockedbyclient");
      }
    });

    const page = await context.newPage();
    apiEvidence = attachApiEvidence(page, options.baseUrl.origin);
    page.on("pageerror", (error) => pageErrors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    await page.goto(options.baseUrl.href, { waitUntil: "domcontentloaded", timeout: 30_000 });
    await page.getByRole("heading", { name: "Tell us what matters. We’ll narrow the noise." }).waitFor({ state: "visible", timeout: 30_000 });

    const modeSelect = page.getByLabel("Shopping mode");
    await modeSelect.waitFor({ state: "visible", timeout: UI_TIMEOUT_MS });
    if (await modeSelect.inputValue() !== "offline") {
      await modeSelect.selectOption("offline");
      await page.locator(".status-pill", { hasText: "Offline" }).waitFor({ state: "visible", timeout: UI_TIMEOUT_MS });
    }
    check(await modeSelect.inputValue() === "offline", "the browser UI could not be forced to Offline benchmark mode");
    check(((await page.locator(".status-pill").textContent()) ?? "").includes("Offline"), "the visible mode status did not report Offline");
    check(await page.getByRole("button", { name: "Open shortlist with 0 products" }).isVisible(), "fresh browser context did not begin with an empty shortlist");
    assertions.offline_mode = true;
    const initialSessionExchange = await waitForAsync("initial offline API session evidence", async () => {
      await apiEvidence.settle();
      return successfulSessionCreations(apiEvidence.exchanges)[0];
    });
    check(initialSessionExchange.request?.mode === "offline", "initial UI session was not created in Offline mode");
    check(initialSessionExchange.request?.marketplace === "SG", "initial UI session did not use the SG marketplace");
    check(initialSessionExchange.response?.mode === "offline", "initial API response did not confirm Offline mode");
    check(initialSessionExchange.response?.turn === 0, "initial API response did not begin at turn zero");
    assertions.initial_session = {
      mode: "offline",
      marketplace: "SG",
      turn: 0,
      session_id_sha256: initialSessionExchange.response.session_id_sha256,
      exchange_sequence: initialSessionExchange.sequence,
    };

    await installVisibleCursor(page);
    const cdp = await context.newCDPSession(page);
    recorder = new ScreencastRecorder({ cdp, output: stagedOutput, ffmpeg });
    await recorder.start();
    await runStoryboard({
      page,
      recorder,
      events,
      assertions,
      interrupted,
      apiEvidence,
      initialSessionExchange,
    });
    await apiEvidence.settle();
    const recorderResult = await recorder.stop();
    recorder = null;

    check(pageErrors.length === 0, `browser page errors occurred: ${pageErrors.join(" | ")}`);
    check(consoleErrors.length === 0, `browser console errors occurred: ${consoleErrors.join(" | ")}`);
    check(blockedUrls.length === 0, `the app attempted non-loopback requests: ${[...new Set(blockedUrls)].join(", ")}`);

    const media = probeVideo(ffprobe, stagedOutput);
    const outputHash = await sha256File(stagedOutput);
    const sourceHash = await sha256File(SCRIPT_PATH);
    const lockHash = await sha256File(path.join(RECORDING_DIR, "package-lock.json"));
    const manifest = {
      schema_version: 1,
      storyboard_id: "shopping-copilot-live-v1",
      created_at_utc: new Date().toISOString(),
      base_url: options.baseUrl.href,
      capture: {
        target_duration_seconds: TARGET_DURATION_SECONDS,
        width: WIDTH,
        height: HEIGHT,
        fps: FPS,
        jpeg_quality: JPEG_QUALITY,
        codec: "h264",
        crf: CRF,
        audio: false,
        frames_written: recorderResult.frames_written,
        source_frames_received: recorderResult.source_frames_received,
        changed_source_frames: recorderResult.changed_source_frames,
        acknowledgments_started: recorderResult.acknowledgments_started,
        acknowledgments_completed: recorderResult.acknowledgments_completed,
        source_frame_age_at_stop_seconds: recorderResult.source_frame_age_at_stop_seconds,
        change_checkpoints: recorderResult.change_checkpoints,
        source_frame: recorderResult.source_frame,
        first_frame_metadata: recorderResult.first_frame_metadata,
      },
      health,
      runtime: {
        node: process.version,
        playwright: playwrightPackage.version,
        chromium: browser.version(),
        chromium_executable: chromium.executablePath(),
        ffmpeg: ffmpegVersion,
        ffprobe: ffprobeVersion,
        platform: process.platform,
        architecture: process.arch,
        os_release: os.release(),
      },
      assertions,
      network: {
        policy: `exact-origin-only:${options.baseUrl.origin}`,
        blocked_non_loopback_count: blockedUrls.length,
        blocked_urls: [...new Set(blockedUrls)],
      },
      diagnostics: {
        page_errors: pageErrors,
        console_errors: consoleErrors,
      },
      api_exchanges: apiEvidence.exchanges,
      events,
      inputs: {
        recorder_sha256: sourceHash,
        package_lock_sha256: lockHash,
      },
      output: {
        path: options.output,
        ...media,
        sha256: outputHash,
      },
    };
    await fs.writeFile(stagedManifest, `${JSON.stringify(manifest, null, 2)}\n`, { encoding: "utf8", flag: "wx" });
    await fs.rename(stagedOutput, options.output);
    await fs.rename(stagedManifest, options.manifest);
    process.stdout.write(`${JSON.stringify({ video: options.output, manifest: options.manifest, ...media, sha256: outputHash }, null, 2)}\n`);
    return 0;
  } finally {
    process.removeListener("SIGINT", onSigint);
    process.removeListener("SIGTERM", onSigterm);
    apiEvidence?.detach();
    await recorder?.abort().catch(() => undefined);
    await context?.close().catch(() => undefined);
    await browser?.close().catch(() => undefined);
    await fs.unlink(stagedOutput).catch(() => undefined);
    await fs.unlink(stagedManifest).catch(() => undefined);
  }
}


export {
  RecordingError,
  ScreencastRecorder,
  attachApiEvidence,
  captureApiExchange,
  successfulSessionCreations,
};


if (process.argv[1] && path.resolve(process.argv[1]) === SCRIPT_PATH) {
  main().then(
    (code) => { process.exitCode = code; },
    (error) => {
      const message = error instanceof Error ? error.message : String(error);
      process.stderr.write(`Live demo recording failed: ${message}\n`);
      process.exitCode = 2;
    },
  );
}
