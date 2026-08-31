import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import App, { artClass, productVisual } from "./App";
import type {
  ExpertState,
  HealthResponse,
  Product,
  SessionResponse,
  TurnResponse,
} from "./types";

const health: HealthResponse = {
  status: "ready",
  catalog_count: 50_000,
  max_turns: 10,
  agent_contract: "starter.agent.Agent",
  hybrid_available: true,
  hybrid_model: "gpt-5.6-terra",
  startup_seconds: 1.25,
  marketplaces: [
    { code: "SG", label: "Singapore", domain: "www.amazon.sg" },
    { code: "US", label: "United States", domain: "www.amazon.com" },
  ],
};

const expertState: ExpertState = {
  turn: 0,
  intent_generation: 0,
  route_probabilities: { buying: 0.7, browsing: 0.2, focused: 0.1 },
  slots: {},
  no_preferences: [],
  profile_priors: [],
  hard_constraints: [],
  soft_preferences: [],
  previously_shown_count: 0,
  openai_calls: 0,
  next_attribute: null,
  latency_ms: 14,
  enhancement: {
    requested: true,
    status: "available",
    outcome: "not_attempted",
    enabled: true,
    attempted: false,
    applied: false,
    model: "gpt-5.6-terra",
    reasoning_effort: "low",
    calls_used: 0,
    max_calls: 10,
    timeout_seconds: 6,
    rank_blend: 0.65,
    latency_ms: 0,
    prompt_tokens: 0,
    completion_tokens: 0,
    used_mode: "offline_fallback",
    fallback_reason: "OPENAI_API_KEY is not configured",
  },
  retrieval: ["structured facets", "FTS5", "dense intent vectors"],
};

const session: SessionResponse = {
  session_id: "session-123",
  turn: 0,
  max_turns: 10,
  status: "active",
  mode: "offline",
  marketplace: "SG",
  expert_state: expertState,
};

const products: Product[] = [
  {
    rank: 1,
    parent_asin: "B001TEST01",
    title: "Harbor Leather Daypack",
    price: 48.5,
    store: "Harbor Goods",
    categories: ["Backpacks", "Casual Daypacks"],
    category: "Casual Daypacks",
    features: ["Full-grain leather", "Padded laptop sleeve"],
    details: { Material: "Leather" },
    average_rating: 4.7,
    rating_number: 312,
    match_reasons: ["Matches leather must-have", "Within the requested category"],
    amazon_url: "https://www.amazon.sg/dp/B001TEST01",
    data_source: "techjam_catalog_snapshot",
    is_live: false,
  },
  {
    rank: 2,
    parent_asin: "B001TEST02",
    title: "Cedar Commuter Backpack",
    price: 42,
    store: "Cedar Supply",
    categories: ["Backpacks", "Casual Daypacks"],
    category: "Casual Daypacks",
    features: ["Leather trim", "Water-resistant lining"],
    details: { Material: "Canvas and leather" },
    average_rating: 4.5,
    rating_number: 186,
    match_reasons: ["Strong leather relevance", "Diversifies the shortlist"],
    amazon_url: "https://www.amazon.sg/dp/B001TEST02",
    data_source: "techjam_catalog_snapshot",
    is_live: false,
  },
];

const rotatedProducts: Product[] = products.map((product, index) => ({
  ...product,
  rank: index + 1,
  parent_asin: `B009NEXT0${index + 1}`,
  title: index === 0 ? "Northstar Travel Pack" : "Juniper Everyday Carry",
  amazon_url: `https://www.amazon.sg/dp/B009NEXT0${index + 1}`,
}));

function turnResponse(
  turn: number,
  quickReplies: TurnResponse["experience"]["quick_replies"] = [],
  resultProducts: Product[] = products,
): TurnResponse {
  return {
    session_id: session.session_id,
    turn,
    max_turns: 10,
    status: "active",
    agent_response: {
      message: turn === 1
        ? "I found two strong matches. Would you like to narrow by color?"
        : "No color preference noted. I kept the strongest overall matches.",
      ask_attribute: turn === 1 ? "color" : null,
      recommendations: resultProducts.map(({ parent_asin }) => ({ parent_asin })),
      usage: { prompt_tokens: 0, completion_tokens: 0 },
    },
    products: resultProducts,
    experience: {
      quick_replies: quickReplies,
      snapshot_disclosure: "Fixed challenge catalog snapshot.",
      amazon_disclosure: "Verify current listing details on Amazon.",
    },
    expert_state: {
      ...expertState,
      turn,
      hard_constraints: ["category: casual daypacks", "material: leather"],
      previously_shown_count: resultProducts.length,
      next_attribute: turn === 1 ? "color" : null,
      latency_ms: 23,
    },
    meta: {
      latency_ms: 23,
      requested_mode: "offline",
      used_mode: "offline",
      fallback_reason: null,
      idempotency_replay: false,
      estimated_cost_usd: 0,
    },
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function installApi(
  turns: TurnResponse[] = [],
  options: {
    healthResponse?: HealthResponse;
    failSessionNumber?: number;
    messageSequence?: Array<{ status: number; body: unknown }>;
  } = {},
): ReturnType<typeof vi.fn> {
  let turnIndex = 0;
  let sessionIndex = 0;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "/api/health") return jsonResponse(options.healthResponse ?? health);
    if (url === "/api/sessions" && init?.method === "POST") {
      sessionIndex += 1;
      if (sessionIndex === options.failSessionNumber) {
        return jsonResponse({ error: { code: "SESSION_CREATE_FAILED", message: "The requested session could not be created." } }, 503);
      }
      const body = JSON.parse(String(init.body)) as { mode: SessionResponse["mode"]; marketplace: string };
      return jsonResponse({ ...session, mode: body.mode, marketplace: body.marketplace });
    }
    if (url === `/api/sessions/${session.session_id}/messages` && init?.method === "POST") {
      const sequenced = options.messageSequence?.[turnIndex];
      if (options.messageSequence) {
        turnIndex += 1;
        if (!sequenced) throw new Error("Unexpected message request in test");
        return jsonResponse(sequenced.body, sequenced.status);
      }
      const response = turns[turnIndex];
      turnIndex += 1;
      if (!response) throw new Error("Unexpected message request in test");
      return jsonResponse(response);
    }
    if (url === `/api/sessions/${session.session_id}` && init?.method === "DELETE") {
      return new Response(null, { status: 204 });
    }
    throw new Error(`Unexpected API request: ${init?.method ?? "GET"} ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function messagePayloads(fetchMock: ReturnType<typeof vi.fn>): Array<Record<string, unknown>> {
  return fetchMock.mock.calls
    .filter(([url, init]) => String(url).endsWith("/messages") && (init as RequestInit | undefined)?.method === "POST")
    .map(([, init]) => JSON.parse(String((init as RequestInit).body)) as Record<string, unknown>);
}

async function renderReadyApp() {
  render(<App />);
  await screen.findByRole("heading", { name: "Tell us what matters. We’ll narrow the noise." });
}

describe("Shopping Copilot web experience", () => {
  it("derives truthful, stable artwork from the category path rather than title fragments or rank", () => {
    const apparelProduct: Product = {
      ...products[0],
      title: "Spring Drawstring Capris",
      category: "Raincoats",
      categories: ["Clothing, Shoes & Jewelry", "Women", "Raincoats"],
    };

    expect(productVisual(apparelProduct)).toMatchObject({ family: "Apparel", familyKey: "apparel", marker: "WEAR" });
    expect(artClass({ ...apparelProduct, rank: 9 })).toBe(artClass({ ...apparelProduct, rank: 1 }));
  });

  it("defaults a key-present server to an offline Singapore session with pre-send privacy", async () => {
    const fetchMock = installApi();

    await renderReadyApp();

    expect(screen.getByText("Turn 0 / 10")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Hybrid" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Shopping mode" })).toHaveValue("offline");
    expect(screen.getByRole("option", { name: "www.amazon.sg · Singapore links" })).toBeInTheDocument();
    expect(screen.getByText("Offline mode keeps your messages and preferences on this Mac. Nothing is sent to OpenAI.")).toBeVisible();

    const sessionCall = fetchMock.mock.calls.find(([url]) => String(url) === "/api/sessions");
    expect(sessionCall).toBeDefined();
    const body = JSON.parse(String((sessionCall?.[1] as RequestInit).body)) as Record<string, unknown>;
    expect(body).toMatchObject({ mode: "offline", marketplace: "SG", preference_tags: [] });
    expect(body.request_id).toEqual(expect.any(String));
    expect((fetchMock.mock.calls[0][1] as RequestInit).signal).toBeDefined();
  });

  it("turns a starter journey into ranked, actionable product results", async () => {
    const fetchMock = installApi([turnResponse(1, [
      { label: "No color preference", message: "I don't have a preference for color." },
    ])]);
    const user = userEvent.setup();
    await renderReadyApp();

    await user.click(screen.getByRole("button", { name: /I know what I need/i }));

    await screen.findByText("I found two strong matches. Would you like to narrow by color?");
    expect(screen.getAllByTestId("product-card")).toHaveLength(2);
    expect(screen.getByRole("heading", { name: "Harbor Leather Daypack" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open details for Harbor Leather Daypack" }))
      .toHaveAccessibleDescription("Illustrative category art for Casual Daypacks; product photo unavailable.");
    expect(screen.getAllByText("Category art")[0]).toBeVisible();
    expect(screen.getByText("Turn 1 / 10")).toBeInTheDocument();
    expect(messagePayloads(fetchMock)[0]).toMatchObject({
      message: "I'm looking for Backpacks Casual Daypacks. A key requirement is: leather.",
      expected_turn: 1,
    });
  });

  it("sends an exact quick reply as the next server-owned turn", async () => {
    const exactReply = "I don't have a preference for color.";
    const fetchMock = installApi([
      turnResponse(1, [{ label: "No color preference", message: exactReply }]),
      turnResponse(2),
    ]);
    const user = userEvent.setup();
    await renderReadyApp();

    await user.click(screen.getByRole("button", { name: /I know what I need/i }));
    await user.click(await screen.findByRole("button", { name: "No color preference" }));

    await screen.findByText("No color preference noted. I kept the strongest overall matches.");
    expect(screen.getByText("Turn 2 / 10")).toBeInTheDocument();
    const payloads = messagePayloads(fetchMock);
    expect(payloads).toHaveLength(2);
    expect(payloads[1]).toMatchObject({ message: exactReply, expected_turn: 2 });
    expect(payloads[1].request_id).toEqual(expect.any(String));
  });

  it("locks alternate turns and preserves the original UUID until an exact retry succeeds", async () => {
    const fetchMock = installApi([], {
      messageSequence: [
        {
          status: 500,
          body: {
            error: {
              code: "ADAPTER_FAILURE_RETRYABLE",
              message: "The result was preserved, but the web view could not be assembled. Retry the same turn safely.",
            },
          },
        },
        {
          status: 409,
          body: {
            error: {
              code: "PENDING_REQUEST_RETRY_REQUIRED",
              message: "An earlier result is preserved but unfinished. Retry that same request before sending another message.",
              expected_next_turn: 1,
            },
          },
        },
        { status: 200, body: turnResponse(1) },
      ],
    });
    const user = userEvent.setup();
    await renderReadyApp();

    await user.click(screen.getByRole("button", { name: "Change direction" }));
    const overrideInput = screen.getByRole("textbox", { name: "What should replace your earlier preference?" });
    await user.type(overrideInput, "an alternate request that must remain blocked");
    const starters = screen.getAllByRole("button", { name: /I know what I need|Help me explore|Change direction|Use your judgment/i });
    await user.click(screen.getByRole("button", { name: /I know what I need/i }));

    const retry = await screen.findByRole("button", { name: "Retry the same turn safely" });
    const firstPayload = messagePayloads(fetchMock)[0];
    expect(firstPayload.request_id).toEqual(expect.any(String));
    starters.forEach((starter) => expect(starter).toBeDisabled());
    expect(screen.getByRole("textbox", { name: "Describe what you are shopping for" })).toBeDisabled();
    expect(overrideInput).toBeDisabled();
    expect(screen.getByRole("button", { name: "Apply change" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Change direction" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Different options" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Restart" })).toBeEnabled();
    expect(retry).toBeEnabled();

    await user.click(screen.getByRole("button", { name: /Help me explore/i }));
    await user.click(screen.getByRole("button", { name: "Apply change" }));
    expect(messagePayloads(fetchMock)).toHaveLength(1);

    await user.click(retry);
    expect(await within(screen.getByLabelText("Conversation transcript")).findByText(/An earlier result is preserved but unfinished/i)).toBeInTheDocument();
    expect(messagePayloads(fetchMock)).toHaveLength(2);
    expect(messagePayloads(fetchMock)[1]).toEqual(firstPayload);
    expect(screen.getByRole("button", { name: "Retry the same turn safely" })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "Retry the same turn safely" }));
    await screen.findByText("I found two strong matches. Would you like to narrow by color?");
    const payloads = messagePayloads(fetchMock);
    expect(payloads).toHaveLength(3);
    expect(payloads[2]).toEqual(firstPayload);
    expect(screen.queryByRole("button", { name: "Retry the same turn safely" })).not.toBeInTheDocument();
    expect(screen.getByText("Turn 1 / 10")).toBeInTheDocument();
  });

  it("keeps compared product objects available after a later turn rotates the results", async () => {
    installApi([
      turnResponse(1, [{ label: "Show different picks", message: "Show me different options." }]),
      turnResponse(2, [], rotatedProducts),
    ]);
    const user = userEvent.setup();
    await renderReadyApp();

    await user.click(screen.getByRole("button", { name: /I know what I need/i }));
    const firstTurnCards = await screen.findAllByTestId("product-card");
    await user.click(within(firstTurnCards[0]).getByRole("button", { name: "Compare" }));
    await user.click(within(firstTurnCards[1]).getByRole("button", { name: "Compare" }));
    await user.click(screen.getByRole("button", { name: "Show different picks" }));

    await screen.findByRole("heading", { name: "Northstar Travel Pack" });
    expect(screen.getByRole("heading", { name: "Juniper Everyday Carry" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Compare products" }));

    const dialog = screen.getByRole("dialog", { name: "Compare products" });
    expect(within(dialog).getByText("Harbor Leather Daypack")).toBeInTheDocument();
    expect(within(dialog).getByText("Cedar Commuter Backpack")).toBeInTheDocument();
  });

  it("requires explicit per-session consent before hybrid messages can leave the Mac", async () => {
    const fetchMock = installApi([turnResponse(1)]);
    const user = userEvent.setup();
    await renderReadyApp();

    await user.selectOptions(screen.getByRole("combobox", { name: "Shopping mode" }), "hybrid");
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Shopping mode" })).toHaveValue("hybrid"));

    expect(screen.getByText(/summaries of up to 30 valid catalog candidates/i)).toBeVisible();
    const consent = screen.getByRole("checkbox", { name: /I consent to send this session's shopping context to OpenAI/i });
    const starter = screen.getByRole("button", { name: /I know what I need/i });
    expect(consent).not.toBeChecked();
    expect(starter).toBeDisabled();
    expect(messagePayloads(fetchMock)).toHaveLength(0);

    await user.click(consent);
    expect(starter).toBeEnabled();
    await user.click(starter);

    await screen.findByText("I found two strong matches. Would you like to narrow by color?");
    expect(messagePayloads(fetchMock)).toHaveLength(1);
    const sessionBodies = fetchMock.mock.calls
      .filter(([url]) => String(url) === "/api/sessions")
      .map(([, init]) => JSON.parse(String((init as RequestInit).body)) as Record<string, unknown>);
    expect(sessionBodies.at(-1)).toMatchObject({ mode: "hybrid", marketplace: "SG" });

    await user.click(screen.getByRole("button", { name: "Restart" }));
    await waitFor(() => expect(screen.getByText("Turn 0 / 10")).toBeInTheDocument());
    expect(screen.getByRole("checkbox", { name: /I consent to send this session's shopping context to OpenAI/i })).not.toBeChecked();
  });

  it("keeps hybrid local and ungated when no OpenAI key was loaded", async () => {
    installApi([], { healthResponse: { ...health, hybrid_available: false } });
    const user = userEvent.setup();
    await renderReadyApp();

    await user.selectOptions(screen.getByRole("combobox", { name: "Shopping mode" }), "hybrid");
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Shopping mode" })).toHaveValue("hybrid"));

    expect(screen.getByText(/no OpenAI API key was loaded/i)).toBeVisible();
    expect(screen.queryByRole("checkbox", { name: /consent/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /I know what I need/i })).toBeEnabled();
  });

  it("supports saving and comparing two recommendations", async () => {
    installApi([turnResponse(1)]);
    const user = userEvent.setup();
    await renderReadyApp();

    await user.click(screen.getByRole("button", { name: /I know what I need/i }));
    await screen.findAllByTestId("product-card");

    const cards = screen.getAllByTestId("product-card");
    await user.click(within(cards[0]).getByRole("button", { name: "Save" }));
    expect(within(cards[0]).getByRole("button", { name: "Saved" })).toHaveAttribute("aria-pressed", "true");
    expect(JSON.parse(localStorage.getItem("shopping-copilot-shortlist") ?? "[]")).toHaveLength(1);

    await user.click(within(cards[0]).getByRole("button", { name: "Compare" }));
    await user.click(within(cards[1]).getByRole("button", { name: "Compare" }));
    const compareButton = screen.getByRole("button", { name: "Compare products" });
    expect(compareButton).toBeEnabled();
    await user.click(compareButton);

    const dialog = screen.getByRole("dialog", { name: "Compare products" });
    expect(within(dialog).getByText("Harbor Leather Daypack")).toBeInTheDocument();
    expect(within(dialog).getByText("Cedar Commuter Backpack")).toBeInTheDocument();
    expect(within(dialog).getByText("US$48.50")).toBeInTheDocument();
  });

  it("opens exactly one named saved-product dialog and refreshes its verification domain", async () => {
    installApi([turnResponse(1)]);
    const user = userEvent.setup();
    await renderReadyApp();

    await user.click(screen.getByRole("button", { name: /I know what I need/i }));
    const cards = await screen.findAllByTestId("product-card");
    await user.click(within(cards[0]).getByRole("button", { name: "Save" }));
    await user.selectOptions(screen.getByRole("combobox", { name: "Amazon verification-link marketplace" }), "US");
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Amazon verification-link marketplace" })).toHaveValue("US"));

    const shortlistTrigger = screen.getByRole("button", { name: "Open shortlist with 1 products" });
    await user.click(shortlistTrigger);
    const shortlist = screen.getByRole("dialog", { name: "Your shortlist" });
    const savedArt = within(shortlist).getByRole("button", { name: "Open details for Harbor Leather Daypack" });
    expect(savedArt).toBeInTheDocument();
    await user.click(savedArt);

    expect(screen.queryByRole("dialog", { name: "Your shortlist" })).not.toBeInTheDocument();
    const details = screen.getByRole("dialog", { name: "Product details" });
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    const currentLink = within(details).getByRole("link", { name: "Check the current listing on www.amazon.com ↗" });
    expect(currentLink).toHaveAttribute("href", "https://www.amazon.com/s?k=B001TEST01");
    expect(within(details).getByRole("button", { name: "Close product details" })).toHaveFocus();

    await user.keyboard("{Escape}");
    await waitFor(() => expect(shortlistTrigger).toHaveFocus());
  });

  it("commits marketplace settings only after session creation succeeds", async () => {
    installApi([], { failSessionNumber: 2 });
    const user = userEvent.setup();
    await renderReadyApp();

    const selector = screen.getByRole("combobox", { name: "Amazon verification-link marketplace" });
    await user.selectOptions(selector, "US");

    expect(await screen.findByRole("alert")).toHaveTextContent("Session settings were not changed");
    expect(selector).toHaveValue("SG");
    expect(screen.getByText("Offline mode keeps your messages and preferences on this Mac. Nothing is sent to OpenAI.")).toBeVisible();
  });

  it("filters malformed browser-restored shortlist entries", async () => {
    localStorage.setItem("shopping-copilot-shortlist", JSON.stringify([
      { parent_asin: "javascript:alert(1)", amazon_url: "javascript:alert(1)" },
      products[0],
    ]));
    installApi();
    const user = userEvent.setup();
    await renderReadyApp();

    await user.click(screen.getByRole("button", { name: "Open shortlist with 1 products" }));
    const shortlist = screen.getByRole("dialog", { name: "Your shortlist" });
    expect(within(shortlist).getByText("Harbor Leather Daypack")).toBeInTheDocument();
    expect(within(shortlist).getAllByRole("article")).toHaveLength(1);
  });

  it("reports a local shortlist persistence failure without breaking the session", async () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("Quota exceeded", "QuotaExceededError"); });
    installApi();
    await renderReadyApp();

    expect(await screen.findByRole("status")).toHaveTextContent("could not save the shortlist locally");
    expect(screen.getByRole("button", { name: /I know what I need/i })).toBeEnabled();
  });

  it("traps focus in expert mode, hides the background, and restores focus on Escape", async () => {
    installApi();
    const user = userEvent.setup();
    await renderReadyApp();

    const trigger = screen.getByRole("button", { name: "How it decided" });
    await user.click(trigger);

    const dialog = screen.getByRole("dialog", { name: "How it decided" });
    const close = within(dialog).getByRole("button", { name: "Close expert mode" });
    expect(within(dialog).getByText("Intent signals")).toBeInTheDocument();
    expect(within(dialog).getByText("Off")).toBeInTheDocument();
    expect(within(dialog).getByText("structured facets")).toBeInTheDocument();
    expect(screen.getByTestId("app-content")).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByTestId("app-content")).toHaveAttribute("inert");
    expect(close).toHaveFocus();

    await user.tab({ shift: true });
    expect(within(dialog).getByRole("button", { name: "Apply and restart" })).toHaveFocus();
    await user.tab();
    expect(close).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "How it decided" })).not.toBeInTheDocument();
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(screen.getByTestId("app-content")).not.toHaveAttribute("aria-hidden");
  });

  it("sends an explicit replacement message through the change-direction form", async () => {
    const fetchMock = installApi([turnResponse(1)]);
    const user = userEvent.setup();
    await renderReadyApp();

    await user.click(screen.getByRole("button", { name: "Change direction" }));
    const replacement = screen.getByRole("textbox", { name: "What should replace your earlier preference?" });
    await user.type(replacement, "lightweight canvas under $60");
    await user.click(screen.getByRole("button", { name: "Apply change" }));

    await screen.findByText("I found two strong matches. Would you like to narrow by color?");
    expect(messagePayloads(fetchMock)[0]).toMatchObject({
      message: "Actually, ignore my earlier preference. What I need is: lightweight canvas under $60.",
      expected_turn: 1,
    });
  });
});
