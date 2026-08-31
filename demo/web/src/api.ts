import type { HealthResponse, SessionResponse, ShoppingMode, TurnResponse } from "./types";

const API_TIMEOUT_MS = 12_000;

interface ErrorEnvelope {
  error?: {
    code?: string;
    message?: string;
    expected_next_turn?: number;
  };
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly expectedNextTurn?: number;

  constructor(status: number, payload: ErrorEnvelope) {
    super(payload.error?.message ?? "The local service returned an unexpected error.");
    this.name = "ApiError";
    this.status = status;
    this.code = payload.error?.code ?? "UNKNOWN_ERROR";
    this.expectedNextTurn = payload.error?.expected_next_turn;
  }
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      signal: AbortSignal.timeout(API_TIMEOUT_MS),
      headers: {
        "Content-Type": "application/json",
        ...init?.headers,
      },
    });
  } catch (error) {
    if (error instanceof DOMException && (error.name === "TimeoutError" || error.name === "AbortError")) {
      throw new Error("The local service took too long to respond. You can retry the same turn safely.");
    }
    throw error;
  }
  if (!response.ok) {
    let payload: ErrorEnvelope = {};
    try {
      payload = (await response.json()) as ErrorEnvelope;
    } catch {
      // Preserve a safe generic message when a proxy returns non-JSON content.
    }
    throw new ApiError(response.status, payload);
  }
  return (await response.json()) as T;
}

export function getHealth(): Promise<HealthResponse> {
  return requestJson<HealthResponse>("/api/health");
}

export function createSession(options: {
  requestId: string;
  mode: ShoppingMode;
  marketplace: string;
  preferenceTags: string[];
}): Promise<SessionResponse> {
  return requestJson<SessionResponse>("/api/sessions", {
    method: "POST",
    body: JSON.stringify({
      request_id: options.requestId,
      mode: options.mode,
      marketplace: options.marketplace,
      preference_tags: options.preferenceTags,
    }),
  });
}

export function sendMessage(options: {
  sessionId: string;
  requestId: string;
  message: string;
  expectedTurn: number;
}): Promise<TurnResponse> {
  return requestJson<TurnResponse>(`/api/sessions/${options.sessionId}/messages`, {
    method: "POST",
    body: JSON.stringify({
      request_id: options.requestId,
      message: options.message,
      expected_turn: options.expectedTurn,
    }),
  });
}

export async function deleteSession(sessionId: string): Promise<void> {
  await fetch(`/api/sessions/${sessionId}`, {
    method: "DELETE",
    signal: AbortSignal.timeout(API_TIMEOUT_MS),
  });
}
