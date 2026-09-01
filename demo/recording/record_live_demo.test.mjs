import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import test from "node:test";

import {
  ScreencastRecorder,
  attachApiEvidence,
  successfulSessionCreations,
} from "./record_live_demo.mjs";


function sourceEvent(value, sessionId = 1) {
  return {
    data: Buffer.from(value).toString("base64"),
    metadata: { deviceWidth: 1920, deviceHeight: 1080 },
    sessionId,
  };
}


test("an initial CDP acknowledgment failure is fatal", async () => {
  const recorder = new ScreencastRecorder({
    cdp: { send: async () => { throw new Error("ack rejected"); } },
    output: "/private/tmp/not-written.mp4",
    ffmpeg: "ffmpeg",
  });
  recorder.onFrame(sourceEvent("first-frame"));
  await assert.rejects(recorder.settleAcks(), /browser screencast failed: ack rejected/);
  assert.equal(recorder.sourceFramesReceived, 1);
  assert.equal(recorder.acksStarted, 1);
  assert.equal(recorder.acksCompleted, 0);
});


test("source telemetry distinguishes repeated frames and requires a later change", async () => {
  const recorder = new ScreencastRecorder({
    cdp: { send: async () => undefined },
    output: "/private/tmp/not-written.mp4",
    ffmpeg: "ffmpeg",
  });
  recorder.onFrame(sourceEvent("same-frame", 1));
  recorder.onFrame(sourceEvent("same-frame", 2));
  await recorder.settleAcks();
  assert.equal(recorder.sourceFramesReceived, 2);
  assert.equal(recorder.changedSourceFrames, 1);
  assert.equal(recorder.acksCompleted, 2);

  const checkpoint = recorder.sourceCheckpoint();
  setTimeout(() => recorder.onFrame(sourceEvent("changed-frame", 3)), 10);
  const evidence = await recorder.requireChangedFrameAfter(checkpoint, "unit-test scene", 250);
  await recorder.settleAcks();
  assert.equal(evidence.changed_source_frames, 2);
  assert.equal(recorder.acksCompleted, 3);

  const frozenCheckpoint = recorder.sourceCheckpoint();
  await assert.rejects(
    recorder.requireChangedFrameAfter(frozenCheckpoint, "frozen scene", 60),
    /timed out waiting for frozen scene in the captured browser stream/,
  );
});


function sessionResponse(page, sessionId, sequence) {
  const body = Buffer.from(JSON.stringify({
    session_id: sessionId,
    turn: 0,
    mode: "offline",
    expert_state: { intent_generation: 0, route_probabilities: { override: 0 } },
  }));
  const request = {
    method: () => "POST",
    postData: () => JSON.stringify({
      request_id: `00000000-0000-4000-8000-${String(sequence).padStart(12, "0")}`,
      mode: "offline",
      marketplace: "SG",
      preference_tags: [],
    }),
  };
  page.emit("response", {
    url: () => "http://127.0.0.1:8765/api/sessions",
    status: () => 201,
    request: () => request,
    body: async () => body,
  });
}


test("API evidence proves restart session IDs differ without retaining raw IDs", async () => {
  const page = new EventEmitter();
  const evidence = attachApiEvidence(page, "http://127.0.0.1:8765");
  const first = "a".repeat(32);
  const second = "b".repeat(32);
  sessionResponse(page, first, 1);
  sessionResponse(page, second, 2);
  await evidence.settle();
  const creations = successfulSessionCreations(evidence.exchanges);
  assert.equal(creations.length, 2);
  assert.notEqual(creations[0].response.session_id_sha256, creations[1].response.session_id_sha256);
  assert.equal(creations[0].request.mode, "offline");
  assert.equal(creations[1].request.marketplace, "SG");
  const serialized = JSON.stringify(evidence.exchanges);
  assert.equal(serialized.includes(first), false);
  assert.equal(serialized.includes(second), false);
  evidence.detach();
});
