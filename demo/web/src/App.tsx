import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, FormEvent } from "react";
import { ApiError, createSession, deleteSession, getHealth, sendMessage } from "./api";
import type {
  ChatMessage,
  HealthResponse,
  Product,
  QuickReply,
  SessionResponse,
  ShoppingMode,
  TurnResponse,
} from "./types";

type DialogState =
  | { kind: "expert" }
  | { kind: "shortlist" }
  | { kind: "compare" }
  | { kind: "detail"; product: Product };

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

const STARTERS = [
  {
    label: "I know what I need",
    detail: "Start with a must-have",
    marker: "01",
    prompt: "I'm looking for Backpacks Casual Daypacks. A key requirement is: leather.",
  },
  {
    label: "Help me explore",
    detail: "Start broad, then narrow",
    marker: "02",
    prompt: "I'm looking for Basketball Men, but I'm still exploring.",
  },
  {
    label: "Change direction",
    detail: "Replace an earlier preference",
    marker: "03",
    prompt: "I'm looking for Rain & Anoraks Anoraks. Department: womens",
  },
  {
    label: "Use your judgment",
    detail: "Skip an attribute gracefully",
    marker: "04",
    prompt: "I'm looking for Socks & Hosiery Leg Warmers, but I'm still exploring.",
  },
];

interface PendingTurn {
  requestId: string;
  message: string;
  expectedTurn: number;
}

function makeId(): string {
  return crypto.randomUUID();
}

function formatPrice(price: number | null): string {
  return price === null ? "Snapshot price unavailable" : `US$${price.toFixed(2)}`;
}

function formatCost(cost: number): string {
  return cost ? `$${cost.toFixed(6)}` : "$0.000000";
}

interface ProductVisual {
  family: string;
  familyKey: string;
  marker: string;
  palette: number;
}

const PRODUCT_FAMILIES = [
  { family: "Footwear", familyKey: "footwear", marker: "STEP", pattern: /\b(?:shoes?|boots?|sandals?|sneakers?|slippers?|footwear|loafers?|heels?)\b/ },
  { family: "Jewelry", familyKey: "jewelry", marker: "GEM", pattern: /\b(?:jewelry|jewellery|jewels?|necklaces?|earrings?|bracelets?|pendants?|brooch(?:es)?|anklets?|rings?)\b/ },
  { family: "Watches", familyKey: "watches", marker: "TIME", pattern: /\b(?:watches?|timepieces?)\b/ },
  { family: "Bags & travel", familyKey: "bags", marker: "CARRY", pattern: /\b(?:bags?|backpacks?|luggage|travel|handbags?|wallets?|purses?|totes?|briefcases?)\b/ },
  { family: "Accessories", familyKey: "accessories", marker: "DETAIL", pattern: /\b(?:accessories|accessory|eyewear|sunglasses?|glasses|belts?|hats?|caps?|scarves|scarfs|gloves?|socks?|hosiery|ties?)\b/ },
  { family: "Costumes", familyKey: "costumes", marker: "STORY", pattern: /\b(?:costumes?|cosplay|novelties|novelty|characters?)\b/ },
  { family: "Apparel", familyKey: "apparel", marker: "WEAR", pattern: /\b(?:apparel|clothing|shirts?|jerseys?|dresses|dress|pants?|shorts?|jackets?|coats?|raincoats?|swimwear|swimsuits?|underwear|lingerie|hoodies?|sweaters?|skirts?|activewear|sportswear|anoraks?|uniforms?|jeans?|leggings?)\b/ },
] as const;

function stableHash(value: string): number {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

export function productVisual(product: Product): ProductVisual {
  const genericRoot = /^\s*clothing\s*,?\s*shoes\s*(?:&|and)\s*jewelry\s*$/i;
  const leafFirstCategories = [product.category, ...[...product.categories].reverse()]
    .map((value) => value.trim().toLowerCase())
    .filter((value, index, values) => value && !genericRoot.test(value) && values.indexOf(value) === index);
  const match = leafFirstCategories
    .map((category) => PRODUCT_FAMILIES.find((candidate) => candidate.pattern.test(category)))
    .find((candidate) => candidate !== undefined);
  const identityHash = stableHash(product.parent_asin.toUpperCase());
  return {
    family: match?.family ?? "Catalog find",
    familyKey: match?.familyKey ?? "other",
    marker: match?.marker ?? "FOUND",
    palette: (identityHash % 6) + 1,
  };
}

export function artClass(product: Product): string {
  const visual = productVisual(product);
  return `category-art art-${visual.palette} family-${visual.familyKey}`;
}

function ProductArtContent({ product, rank }: { product: Product; rank?: number }) {
  const visual = productVisual(product);
  return (
    <>
      {rank !== undefined && <span className="rank">#{rank}</span>}
      <span className="art-label">Category art</span>
      <span className="art-marker" aria-hidden="true">{visual.marker}</span>
      <span className="art-family" aria-hidden="true">{visual.family}</span>
    </>
  );
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isStringRecord(value: unknown): value is Record<string, string> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value)
    && Object.values(value as Record<string, unknown>).every((item) => typeof item === "string");
}

function isSafeAmazonUrl(value: unknown): value is string {
  if (typeof value !== "string") return false;
  try {
    const url = new URL(value);
    const hostname = url.hostname.toLowerCase();
    return url.protocol === "https:" && (hostname === "amazon.com" || hostname.startsWith("www.amazon."));
  } catch {
    return false;
  }
}

function isStoredProduct(value: unknown): value is Product {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const item = value as Partial<Product>;
  return Number.isInteger(item.rank)
    && typeof item.parent_asin === "string"
    && /^[A-Z0-9]{5,20}$/i.test(item.parent_asin)
    && typeof item.title === "string"
    && (item.price === null || (typeof item.price === "number" && Number.isFinite(item.price)))
    && (item.store === null || typeof item.store === "string")
    && isStringArray(item.categories)
    && typeof item.category === "string"
    && isStringArray(item.features)
    && isStringRecord(item.details)
    && typeof item.average_rating === "number"
    && Number.isFinite(item.average_rating)
    && typeof item.rating_number === "number"
    && Number.isFinite(item.rating_number)
    && isStringArray(item.match_reasons)
    && isSafeAmazonUrl(item.amazon_url)
    && item.data_source === "techjam_catalog_snapshot"
    && item.is_live === false;
}

function loadSavedProducts(): Product[] {
  try {
    const parsed = JSON.parse(localStorage.getItem("shopping-copilot-shortlist") ?? "[]") as unknown;
    return Array.isArray(parsed) ? parsed.filter(isStoredProduct).slice(0, 20) : [];
  } catch {
    return [];
  }
}

function verificationUrl(parentAsin: string, domain: string): string {
  return `https://${domain}/s?k=${encodeURIComponent(parentAsin)}`;
}

function downloadText(filename: string, content: string, type: string): void {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function ProductCard({
  product,
  compared,
  saved,
  verificationDomain,
  onCompare,
  onSave,
  onOpen,
}: {
  product: Product;
  compared: boolean;
  saved: boolean;
  verificationDomain: string;
  onCompare: () => void;
  onSave: () => void;
  onOpen: () => void;
}) {
  const artDescriptionId = `product-art-${product.parent_asin.replace(/[^a-z0-9_-]/gi, "-")}`;
  return (
    <article className="product-card" data-testid="product-card">
      <button
        className={`product-art ${artClass(product)}`}
        type="button"
        onClick={onOpen}
        aria-label={`Open details for ${product.title}`}
        aria-describedby={artDescriptionId}
      >
        <ProductArtContent product={product} rank={product.rank} />
        <span className="sr-only" id={artDescriptionId}>Illustrative category art for {product.category || "catalog item"}; product photo unavailable.</span>
      </button>
      <div className="product-body">
        <div className="product-kicker">
          <span>{product.category}</span>
          <button
            type="button"
            className={`save-button ${saved ? "is-saved" : ""}`}
            aria-pressed={saved}
            onClick={onSave}
          >
            {saved ? "Saved" : "Save"}
          </button>
        </div>
        <button type="button" className="product-title-button" onClick={onOpen}>
          <h3>{product.title}</h3>
        </button>
        <div className="product-meta">
          <strong className="price">{formatPrice(product.price)}</strong>
          {product.average_rating > 0 && (
            <span aria-label={`${product.average_rating} out of 5, ${product.rating_number} catalog reviews`}>
              ★ {product.average_rating.toFixed(1)} <small>({product.rating_number.toLocaleString()})</small>
            </span>
          )}
        </div>
        <ul className="reason-list" aria-label="Why this matches">
          {product.match_reasons.map((reason) => <li key={reason}>{reason}</li>)}
        </ul>
        <div className="card-actions">
          <button type="button" className={compared ? "is-selected" : ""} aria-pressed={compared} onClick={onCompare}>
            {compared ? "Comparing" : "Compare"}
          </button>
          <a href={product.amazon_url} target="_blank" rel="noopener noreferrer nofollow" title={`Verify the current listing on ${verificationDomain}`}>
            Check on {verificationDomain} <span aria-hidden="true">↗</span>
          </a>
        </div>
      </div>
    </article>
  );
}

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [bootError, setBootError] = useState<string | null>(null);
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [mode, setMode] = useState<ShoppingMode>("offline");
  const [marketplace, setMarketplace] = useState("SG");
  const [preferenceText, setPreferenceText] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [lastResponse, setLastResponse] = useState<TurnResponse | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [productHistory, setProductHistory] = useState<Record<string, Product>>({});
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [retryRequest, setRetryRequest] = useState<PendingTurn | null>(null);
  const [announcement, setAnnouncement] = useState("Preparing the catalog index.");
  const [operationError, setOperationError] = useState<string | null>(null);
  const [storageError, setStorageError] = useState<string | null>(null);
  const [hybridConsent, setHybridConsent] = useState(false);
  const [dialog, setDialog] = useState<DialogState | null>(null);
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [overrideText, setOverrideText] = useState("");
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [savedProducts, setSavedProducts] = useState<Product[]>(loadSavedProducts);
  const transcriptRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const dialogTriggerRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    try {
      localStorage.setItem("shopping-copilot-shortlist", JSON.stringify(savedProducts.slice(0, 20)));
      setStorageError(null);
    } catch {
      setStorageError("This browser could not save the shortlist locally. Your current session still works, but saved items may not survive a reload.");
    }
  }, [savedProducts]);

  useEffect(() => {
    transcriptRef.current?.scrollTo({ top: transcriptRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, sending]);

  useEffect(() => {
    if (!dialog) {
      const trigger = dialogTriggerRef.current;
      dialogTriggerRef.current = null;
      if (trigger?.isConnected) trigger.focus();
      return;
    }

    const container = dialogRef.current;
    if (!container) return;
    const focusable = () => Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
      .filter((element) => !element.hasAttribute("hidden") && element.getAttribute("aria-hidden") !== "true");
    (focusable()[0] ?? container).focus();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const containFocus = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setDialog(null);
        return;
      }
      if (event.key !== "Tab") return;
      const items = focusable();
      if (items.length === 0) {
        event.preventDefault();
        container.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === container)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", containFocus);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", containFocus);
    };
  }, [dialog]);

  useEffect(() => {
    if (dialog) return;
    const closeOverride = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOverrideOpen(false);
    };
    window.addEventListener("keydown", closeOverride);
    return () => window.removeEventListener("keydown", closeOverride);
  }, [dialog]);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    const boot = async () => {
      try {
        const current = await getHealth();
        if (cancelled) return;
        setHealth(current);
        if (current.status === "failed") {
          setBootError("The catalog index could not start. Check that data/catalog.jsonl is present, then restart the local service.");
          return;
        }
        if (current.status !== "ready") {
          setAnnouncement("Indexing 50,000 catalog products. This usually takes about 17 seconds.");
          timer = window.setTimeout(boot, 800);
          return;
        }
        const created = await createSession({ requestId: makeId(), mode: "offline", marketplace: "SG", preferenceTags: [] });
        if (cancelled) return;
        setSession(created);
        setMode(created.mode);
        setMarketplace(created.marketplace);
        setMessages([{
          id: makeId(), role: "assistant",
          text: "Tell me what you’re shopping for. Start broad, add must-haves, or change your mind at any point.",
        }]);
        setAnnouncement("Shopping Copilot is ready.");
      } catch (error) {
        if (cancelled) return;
        setBootError(error instanceof Error ? error.message : "The local service is unavailable.");
      }
    };

    void boot();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, []);

  const activeExpert = lastResponse?.expert_state ?? session?.expert_state;
  const quickReplies: QuickReply[] = lastResponse?.experience.quick_replies ?? [];
  const marketplaceDomain = health?.marketplaces.find((item) => item.code === marketplace)?.domain ?? "www.amazon.sg";
  const localizeProduct = (product: Product): Product => ({
    ...product,
    amazon_url: verificationUrl(product.parent_asin, marketplaceDomain),
  });
  const displayProducts = useMemo(
    () => products.map(localizeProduct),
    [products, marketplaceDomain],
  );
  const localizedSavedProducts = useMemo(
    () => savedProducts.map(localizeProduct),
    [savedProducts, marketplaceDomain],
  );
  const availableProducts = useMemo(() => {
    const byId = new Map<string, Product>();
    [...localizedSavedProducts, ...Object.values(productHistory).map(localizeProduct), ...displayProducts]
      .forEach((product) => byId.set(product.parent_asin, product));
    return byId;
  }, [displayProducts, localizedSavedProducts, marketplaceDomain, productHistory]);
  const comparedProducts = compareIds.map((id) => availableProducts.get(id)).filter((item): item is Product => Boolean(item));
  const detailProduct = dialog?.kind === "detail" ? dialog.product : null;
  const requiresHybridConsent = mode === "hybrid" && health?.hybrid_available === true;
  const sendingAllowed = !requiresHybridConsent || hybridConsent;
  const newTurnAllowed = sendingAllowed && retryRequest === null;

  function openDialog(next: DialogState, trigger?: HTMLElement) {
    if (!dialogTriggerRef.current) {
      const active = trigger ?? document.activeElement;
      if (active instanceof HTMLElement) dialogTriggerRef.current = active;
    }
    setDialog(next);
  }

  function setDialogNode(node: HTMLElement | null) {
    dialogRef.current = node;
  }

  async function restart(nextMode = mode, nextMarketplace = marketplace, preferenceTags?: string[]) {
    setSending(true);
    setHybridConsent(false);
    setOperationError(null);
    const previousId = session?.session_id;
    try {
      const created = await createSession({
        requestId: makeId(), mode: nextMode, marketplace: nextMarketplace,
        preferenceTags: preferenceTags ?? preferenceText.split(",").map((value) => value.trim()).filter(Boolean).slice(0, 8),
      });
      if (previousId) void deleteSession(previousId).catch(() => undefined);
      setSession(created);
      setMode(created.mode);
      setMarketplace(created.marketplace);
      setLastResponse(null);
      setProducts([]);
      setProductHistory({});
      setCompareIds([]);
      setRetryRequest(null);
      setDialog(null);
      setOverrideOpen(false);
      setMessages([{ id: makeId(), role: "assistant", text: "New search, clean slate. What are you shopping for?" }]);
      setAnnouncement(`New ${created.mode} session ready.`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Could not restart the session.";
      setOperationError(`Session settings were not changed. ${message}`);
      setAnnouncement(`Session settings were not changed. ${message}`);
    } finally {
      setSending(false);
    }
  }

  async function executeTurn(pending: PendingTurn, addUserMessage: boolean) {
    if (!session || sending) return;
    setSending(true);
    if (addUserMessage) {
      setMessages((current) => [...current, { id: makeId(), role: "user", text: pending.message, turn: pending.expectedTurn }]);
    }
    try {
      const response = await sendMessage({
        sessionId: session.session_id, requestId: pending.requestId,
        message: pending.message, expectedTurn: pending.expectedTurn,
      });
      setLastResponse(response);
      setProducts(response.products);
      setProductHistory((current) => {
        const next = { ...current };
        response.products.forEach((product) => { next[product.parent_asin] = product; });
        return next;
      });
      setSession((current) => current ? { ...current, turn: response.turn, status: response.status, expert_state: response.expert_state } : current);
      setRetryRequest(null);
      setMessages((current) => [...current, {
        id: makeId(), role: "assistant", text: response.agent_response.message, turn: response.turn,
      }]);
      const modeText = response.meta.used_mode === "hybrid" ? "Hybrid reranking applied." : response.meta.used_mode === "offline" ? "Offline ranking used." : "Online enhancement unavailable; offline ranking used safely.";
      setAnnouncement(`Turn ${response.turn} complete. ${response.products.length} recommendations. ${modeText}`);
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "The request may not have reached the local service.";
      setMessages((current) => [...current, { id: makeId(), role: "system", text: message, error: true }]);
      if (!(error instanceof ApiError && error.code === "PENDING_REQUEST_RETRY_REQUIRED")) {
        setRetryRequest(pending);
      }
      setAnnouncement(`${message} Retry the preserved turn or restart this session.`);
    } finally {
      setSending(false);
    }
  }

  function submitText(text: string) {
    const cleaned = text.replace(/\s+/g, " ").trim();
    if (!cleaned || !session || session.turn >= session.max_turns) return;
    if (retryRequest) {
      setAnnouncement("Finish the preserved turn with the exact retry, or restart before sending something new.");
      return;
    }
    if (!sendingAllowed) {
      setAnnouncement("Confirm hybrid data sharing before sending this session to OpenAI.");
      return;
    }
    setOperationError(null);
    setInput("");
    void executeTurn({ requestId: makeId(), message: cleaned, expectedTurn: session.turn + 1 }, true);
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    submitText(input);
  }

  function toggleSave(product: Product) {
    const isSaved = savedProducts.some((item) => item.parent_asin === product.parent_asin);
    setSavedProducts((current) => isSaved
      ? current.filter((item) => item.parent_asin !== product.parent_asin)
      : [product, ...current].slice(0, 20));
    setAnnouncement(isSaved ? "Removed from shortlist." : "Saved to shortlist.");
  }

  function toggleCompare(product: Product) {
    setCompareIds((current) => {
      if (current.includes(product.parent_asin)) return current.filter((id) => id !== product.parent_asin);
      if (current.length >= 3) {
        setAnnouncement("Compare supports up to three products. Remove one before adding another.");
        return current;
      }
      return [...current, product.parent_asin];
    });
  }

  function applyOverride() {
    const cleaned = overrideText.replace(/\s+/g, " ").trim();
    if (!cleaned) return;
    setOverrideOpen(false);
    setOverrideText("");
    submitText(`Actually, ignore my earlier preference. What I need is: ${cleaned}.`);
  }

  function exportSession(format: "json" | "markdown") {
    const timestamp = new Date().toISOString();
    if (format === "json") {
      downloadText("shopping-copilot-session.json", JSON.stringify({ timestamp, mode, marketplace, messages, last_response: lastResponse }, null, 2), "application/json");
    } else {
      const body = messages.map((message) => `**${message.role === "user" ? "Shopper" : message.role === "assistant" ? "Copilot" : "System"}:** ${message.text}`).join("\n\n");
      downloadText("shopping-copilot-session.md", `# Shopping Copilot session\n\n- Exported: ${timestamp}\n- Mode: ${mode}\n- Marketplace: ${marketplace}\n\n${body}\n`, "text/markdown");
    }
    setAnnouncement(`Exported session as ${format}.`);
  }

  if (!session || health?.status !== "ready") {
    return (
      <main className="startup-view">
        <div className="brand-mark large" aria-hidden="true">SC</div>
        <div className="eyebrow">LOCAL SHOPPING ENGINE</div>
        <h1>{bootError ? "The catalog needs attention." : "Preparing 50,000 products for conversation."}</h1>
        <p>{bootError ?? "Building field-aware search, structured facets, and the catalog-derived intent index. The page will continue automatically."}</p>
        {!bootError && <div className="loading-track"><span /></div>}
        <div className="startup-meta"><span>Runs on this Mac</span><span>Exact-ASIN retrieval</span><span>Safe offline fallback</span></div>
        {bootError && <button type="button" className="primary-button" onClick={() => window.location.reload()}>Try again</button>}
        <div className="sr-only" aria-live="polite">{announcement}</div>
      </main>
    );
  }

  const modeLabel = lastResponse?.meta.used_mode === "hybrid"
    ? "Hybrid applied"
    : mode === "hybrid" && !health.hybrid_available
      ? "Hybrid unavailable · stays offline"
      : mode === "hybrid"
        ? hybridConsent ? "Hybrid · sharing approved" : "Hybrid · consent required"
        : "Offline · stays on this Mac";

  return (
    <div className="app-shell">
      <div className="app-content" data-testid="app-content" aria-hidden={dialog ? true : undefined} inert={dialog ? true : undefined}>
      <header className="topbar">
        <a className="brand" href="#workspace" aria-label="Shopping Copilot home">
          <span className="brand-mark" aria-hidden="true">SC</span>
          <span><strong>Shopping Copilot</strong><small>50,000 products. One clear shortlist.</small></span>
        </a>
        <div className="topbar-actions">
          <label className="compact-select">
            <span className="sr-only">Shopping mode</span>
            <select value={mode} onChange={(event) => { const next = event.target.value as ShoppingMode; void restart(next, marketplace); }} disabled={sending}>
              <option value="hybrid">Hybrid</option><option value="offline">Offline benchmark</option>
            </select>
          </label>
          <label className="compact-select marketplace-select">
            <span className="sr-only">Amazon verification-link marketplace</span>
            <select value={marketplace} onChange={(event) => { const next = event.target.value; void restart(mode, next); }} disabled={sending}>
              {health.marketplaces.map((item) => <option value={item.code} key={item.code}>{item.domain} · {item.label} links</option>)}
            </select>
          </label>
          <span className={`status-pill ${lastResponse?.meta.used_mode === "hybrid" ? "online" : ""}`}><i /> {modeLabel}</span>
          <button className="secondary-button expert-button" type="button" onClick={(event) => openDialog({ kind: "expert" }, event.currentTarget)}>How it decided</button>
          <button className="icon-button" type="button" onClick={(event) => openDialog({ kind: "shortlist" }, event.currentTarget)} aria-label={`Open shortlist with ${savedProducts.length} products`}>Saved <span>{savedProducts.length}</span></button>
        </div>
      </header>

      <main className="workspace" id="workspace">
        <section className="conversation-panel" aria-label="Shopping conversation">
          <div className="conversation-heading">
            <div><div className="eyebrow">YOUR SHOPPING BRIEF</div><h1>Tell us what matters. We’ll narrow the noise.</h1></div>
            <span className="turn-badge">Turn {session.turn} / {session.max_turns}</span>
          </div>
          {activeExpert && (activeExpert.hard_constraints.length > 0 || activeExpert.soft_preferences.length > 0) && (
            <div className="brief-chips" aria-label="Remembered preferences">
              {activeExpert.hard_constraints.map((value) => <span className="hard" key={`hard-${value}`}>{value}</span>)}
              {activeExpert.soft_preferences.slice(0, 5).map((value) => <span key={`soft-${value}`}>{value}</span>)}
            </div>
          )}
          <div className="transcript" ref={transcriptRef} aria-label="Conversation transcript">
            {messages.map((message) => (
              <div className={`message ${message.role}-message ${message.error ? "error-message" : ""}`} key={message.id}>
                <span className="message-role">{message.role === "user" ? "You" : message.role === "assistant" ? "Copilot" : "Notice"}</span>{message.text}
              </div>
            ))}
            {sending && <div className="message assistant-message thinking"><span /><span /><span /><span className="sr-only">Searching and reranking</span></div>}
          </div>
          <div className="privacy-disclosure" role="note" aria-label="Privacy before you send">
            <strong>Privacy before you send</strong>
            {mode === "offline" ? (
              <p>Offline mode keeps your messages and preferences on this Mac. Nothing is sent to OpenAI.</p>
            ) : health.hybrid_available ? (
              <>
                <p>Hybrid mode sends your message, distilled shopping preferences, and summaries of up to 30 valid catalog candidates to OpenAI for optional reranking. Catalog validation and final safeguards stay local.</p>
                <label className="consent-check">
                  <input type="checkbox" checked={hybridConsent} onChange={(event) => setHybridConsent(event.target.checked)} disabled={sending} />
                  <span>I consent to send this session&apos;s shopping context to OpenAI.</span>
                </label>
              </>
            ) : (
              <p>Hybrid enhancement is unavailable because no OpenAI API key was loaded. This session safely stays local with offline ranking; nothing is sent to OpenAI.</p>
            )}
          </div>
          {operationError && <div className="operation-error" role="alert">{operationError}</div>}
          {storageError && <div className="operation-error" role="status">{storageError}</div>}
          {session.turn === 0 && (
            <div className="starter-grid" aria-label="Example shopping journeys">
              {STARTERS.map((starter) => (
                <button type="button" key={starter.marker} onClick={() => submitText(starter.prompt)} disabled={sending || !newTurnAllowed}>
                  <span>{starter.marker}</span><strong>{starter.label}</strong><small>{starter.detail}</small>
                </button>
              ))}
            </div>
          )}
          {quickReplies.length > 0 && session.turn < session.max_turns && (
            <div className="quick-replies" aria-label="Suggested replies">
              {quickReplies.map((reply) => <button type="button" key={`${reply.label}-${reply.message}`} onClick={() => submitText(reply.message)} disabled={sending || !newTurnAllowed}>{reply.label}</button>)}
            </div>
          )}
          {retryRequest && <button className="retry-button" type="button" onClick={() => void executeTurn(retryRequest, false)} disabled={sending}>Retry the same turn safely</button>}
          {overrideOpen && (
            <div className="override-box"><label htmlFor="override-input">What should replace your earlier preference?</label><div><input id="override-input" value={overrideText} onChange={(event) => setOverrideText(event.target.value)} maxLength={300} autoFocus disabled={sending || retryRequest !== null} /><button type="button" onClick={applyOverride} disabled={sending || !newTurnAllowed}>Apply change</button></div></div>
          )}
          <form className="composer" onSubmit={handleSubmit}>
            <label className="sr-only" htmlFor="message">Describe what you are shopping for</label>
            <textarea id="message" placeholder="Try ‘a leather backpack under $50’" value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); if (input.trim()) submitText(input); } }} maxLength={1000} rows={2} disabled={sending || retryRequest !== null || session.turn >= session.max_turns} />
            <button type="submit" disabled={!input.trim() || sending || !newTurnAllowed || session.turn >= session.max_turns}>Send</button>
          </form>
          <div className="conversation-tools">
            <button type="button" onClick={() => setOverrideOpen((value) => !value)} disabled={sending || !newTurnAllowed || session.turn >= session.max_turns}>Change direction</button>
            <button type="button" onClick={() => submitText("Those options are not quite right yet. Please show me different options.")} disabled={sending || !newTurnAllowed || products.length === 0 || session.turn >= session.max_turns}>Different options</button>
            <button type="button" onClick={() => void restart()} disabled={sending}>Restart</button>
          </div>
          {session.turn >= session.max_turns && <p className="turn-complete">This ten-turn journey is complete. Save or export your shortlist, then restart for a new search.</p>}
        </section>

        <section className="results-panel" aria-label="Product recommendations">
          <div className="results-heading">
            <div><div className="eyebrow">RANKED FOR YOUR BRIEF</div><h2>{products.length ? "Best matches from your current preferences" : "A shortlist that learns as you talk"}</h2></div>
            <div className="results-utilities"><span className="snapshot-label">TechJam catalog snapshot · not live inventory</span>{messages.length > 1 && <div className="export-menu"><button type="button" onClick={() => exportSession("markdown")}>Export .md</button><button type="button" onClick={() => exportSession("json")}>Export .json</button></div>}</div>
          </div>
          {products.length === 0 ? (
            <div className="empty-results">
              <div className="empty-art"><span>50K</span><i /><i /><i /></div>
              <div><h3>Human conversation in. Ranked products out.</h3><p>Start with a product, a use, or even a vague idea. The Copilot remembers constraints, asks useful questions, and safely handles a change of mind.</p><ul><li>Exact and structured retrieval</li><li>Transparent hybrid reranking</li><li>Ten-turn state with safe overrides</li></ul></div>
            </div>
          ) : (
            <><div className="product-grid">{displayProducts.map((product) => (
              <ProductCard key={product.parent_asin} product={product} compared={compareIds.includes(product.parent_asin)} saved={savedProducts.some((item) => item.parent_asin === product.parent_asin)} verificationDomain={marketplaceDomain} onCompare={() => toggleCompare(product)} onSave={() => toggleSave(product)} onOpen={() => openDialog({ kind: "detail", product })} />
            ))}</div><p className="catalog-disclosure">Results come from a fixed 50,000-item Amazon Reviews 2023 catalog supplied for the challenge. Snapshot prices are in USD. Availability, images, sellers, and product details may have changed. Verification links use {marketplaceDomain}.</p></>
          )}
        </section>
      </main>

      {compareIds.length > 0 && <div className="compare-bar" role="region" aria-label="Product comparison selection"><div><strong>{compareIds.length} of 3 selected</strong><span>{comparedProducts.map((product) => product.title).join(" · ")}</span></div><button type="button" onClick={() => setCompareIds([])}>Clear</button><button type="button" className="primary-button" onClick={(event) => openDialog({ kind: "compare" }, event.currentTarget)} disabled={compareIds.length < 2}>Compare products</button></div>}
      </div>
      <div className="sr-only" aria-live="polite" aria-atomic="true">{announcement}</div>

      {dialog?.kind === "expert" && activeExpert && (
        <div className="drawer-backdrop" onMouseDown={() => setDialog(null)}><aside ref={setDialogNode} tabIndex={-1} className="drawer expert-drawer" role="dialog" aria-modal="true" aria-labelledby="expert-title" onMouseDown={(event) => event.stopPropagation()}>
          <div className="drawer-header"><div><div className="eyebrow">EXPERT MODE</div><h2 id="expert-title">How it decided</h2></div><button type="button" onClick={() => setDialog(null)} aria-label="Close expert mode">Close</button></div>
          <section className="diagnostic-hero"><div><small>Current turn</small><strong>{session.turn} / 10</strong></div><div><small>Intent version</small><strong>v{activeExpert.intent_generation + 1}</strong></div><div><small>Response time</small><strong>{activeExpert.latency_ms.toFixed(0)} ms</strong></div></section>
          <section><h3>Intent signals <small>diagnostic</small></h3><div className="route-bars">{Object.entries(activeExpert.route_probabilities).map(([name, probability]) => <div key={name}><span>{name}</span><i><b style={{ width: `${probability * 100}%` }} /></i><strong>{Math.round(probability * 100)}%</strong></div>)}</div></section>
          <section><h3>Remembered preferences</h3><div className="evidence-groups"><div><span>Must-haves</span>{activeExpert.hard_constraints.length ? activeExpert.hard_constraints.map((value) => <b key={value}>{value}</b>) : <em>None yet</em>}</div><div><span>Preferences</span>{activeExpert.soft_preferences.length ? activeExpert.soft_preferences.map((value) => <b key={value}>{value}</b>) : <em>None yet</em>}</div><div><span>Skipped</span>{activeExpert.no_preferences.length ? activeExpert.no_preferences.map((value) => <b key={value}>{value}</b>) : <em>None</em>}</div></div></section>
          <section className="model-panel"><div className="model-heading"><div><h3>Online enhancement</h3><p>{activeExpert.enhancement.model}</p></div><span className={activeExpert.enhancement.applied ? "success" : "fallback"}>{activeExpert.enhancement.applied ? "Applied" : mode === "hybrid" ? "Safe fallback" : "Off"}</span></div><dl><div><dt>Outcome</dt><dd>{activeExpert.enhancement.outcome.replaceAll("_", " ")}</dd></div><div><dt>Reasoning</dt><dd>{activeExpert.enhancement.reasoning_effort}</dd></div><div><dt>Rank blend</dt><dd>{Math.round(activeExpert.enhancement.rank_blend * 100)}% model</dd></div><div><dt>Calls</dt><dd>{activeExpert.enhancement.calls_used} / {activeExpert.enhancement.max_calls}</dd></div><div><dt>Tokens</dt><dd>{(activeExpert.enhancement.prompt_tokens + activeExpert.enhancement.completion_tokens).toLocaleString()}</dd></div><div><dt>Estimated turn cost</dt><dd>{formatCost(lastResponse?.meta.estimated_cost_usd ?? 0)}</dd></div></dl></section>
          <section><h3>Retrieval signals</h3><div className="retrieval-list">{activeExpert.retrieval.map((value) => <span key={value}>{value}</span>)}</div></section>
          <section className="preferences-section"><h3>Profile preferences <small>new session</small></h3><p>Optional comma-separated tags can gently influence hybrid ranking. They never become hard filters.</p><input aria-label="Profile preference tags" value={preferenceText} onChange={(event) => setPreferenceText(event.target.value)} placeholder="comfort, lightweight, classic" maxLength={240} /><button type="button" onClick={() => { setDialog(null); void restart(mode, marketplace); }} disabled={sending}>Apply and restart</button></section>
        </aside></div>
      )}

      {dialog?.kind === "shortlist" && <div className="drawer-backdrop" onMouseDown={() => setDialog(null)}><aside ref={setDialogNode} tabIndex={-1} className="drawer" role="dialog" aria-modal="true" aria-labelledby="shortlist-title" onMouseDown={(event) => event.stopPropagation()}><div className="drawer-header"><div><div className="eyebrow">DEVICE-LOCAL</div><h2 id="shortlist-title">Your shortlist</h2></div><button type="button" onClick={() => setDialog(null)} aria-label="Close shortlist">Close</button></div><p className="drawer-intro">Saved only in this browser. Nothing is uploaded or added to a cart. Tiles use illustrative category art—not product photos. Current verification links use {marketplaceDomain}.</p>{localizedSavedProducts.length === 0 ? <div className="drawer-empty">Save a product card to keep it here while you explore.</div> : <div className="saved-list">{localizedSavedProducts.map((product) => { const savedArtDescriptionId = `saved-art-${product.parent_asin.replace(/[^a-z0-9_-]/gi, "-")}`; return <article key={product.parent_asin}><button type="button" aria-label={`Open details for ${product.title}`} aria-describedby={savedArtDescriptionId} className={`saved-art ${artClass(product)}`} onClick={() => openDialog({ kind: "detail", product })}><ProductArtContent product={product} /><span className="sr-only" id={savedArtDescriptionId}>Illustrative category art; product photo unavailable.</span></button><div><small>{product.category}</small><strong>{product.title}</strong><span>{formatPrice(product.price)}</span></div><button type="button" onClick={() => toggleSave(product)}>Remove</button></article>; })}</div>}</aside></div>}

      {detailProduct && <div className="drawer-backdrop" onMouseDown={() => setDialog(null)}><aside ref={setDialogNode} tabIndex={-1} className="drawer product-drawer" role="dialog" aria-modal="true" aria-labelledby="product-detail-title" onMouseDown={(event) => event.stopPropagation()}><div className="drawer-header"><div><div className="eyebrow">CATALOG ITEM · #{detailProduct.rank}</div><h2 id="product-detail-title">Product details</h2></div><button type="button" onClick={() => setDialog(null)} aria-label="Close product details">Close</button></div><div className={`detail-art ${artClass(detailProduct)}`} role="img" aria-label={`Illustrative category art for ${detailProduct.category || "catalog item"}; product photo unavailable.`}><ProductArtContent product={detailProduct} /></div><p className="art-disclosure">Illustrative category art—not a product photo. Open the Amazon verification link to check current listing images.</p><span className="product-category">{detailProduct.category}</span><h3 className="detail-title">{detailProduct.title}</h3><div className="detail-price"><strong>{formatPrice(detailProduct.price)}</strong><span>{detailProduct.average_rating ? `★ ${detailProduct.average_rating.toFixed(1)} from ${detailProduct.rating_number.toLocaleString()} catalog reviews` : "No catalog rating"}</span></div><section><h3>Why it surfaced</h3><ul className="detail-list">{detailProduct.match_reasons.map((value) => <li key={value}>{value}</li>)}</ul></section>{detailProduct.features.length > 0 && <section><h3>Snapshot features</h3><ul className="detail-list">{detailProduct.features.map((value) => <li key={value}>{value}</li>)}</ul></section>}{Object.keys(detailProduct.details).length > 0 && <section><h3>Snapshot attributes</h3><dl className="detail-attributes">{Object.entries(detailProduct.details).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl></section>}<a className="amazon-cta" href={detailProduct.amazon_url} target="_blank" rel="noopener noreferrer nofollow">Check the current listing on {marketplaceDomain} ↗</a><p className="drawer-intro">This opens the selected Amazon verification domain so you can check the current listing. No purchase happens in this demo.</p></aside></div>}

      {dialog?.kind === "compare" && <div className="drawer-backdrop" onMouseDown={() => setDialog(null)}><div ref={setDialogNode} tabIndex={-1} className="compare-dialog" role="dialog" aria-modal="true" aria-labelledby="compare-title" onMouseDown={(event) => event.stopPropagation()}><div className="drawer-header"><div><div className="eyebrow">SIDE BY SIDE</div><h2 id="compare-title">Compare products</h2></div><button type="button" onClick={() => setDialog(null)} aria-label="Close comparison">Close</button></div><div className="compare-table" style={{ "--compare-count": comparedProducts.length } as CSSProperties}><div className="compare-label" />{comparedProducts.map((product) => <div className={`compare-product ${artClass(product)}`} key={`head-${product.parent_asin}`}><span className="art-label">Category art</span><small>#{product.rank} · {product.category}</small><strong>{product.title}</strong><span className="sr-only">Illustrative category art; product photo unavailable.</span></div>)}<div className="compare-label">Snapshot price (USD)</div>{comparedProducts.map((product) => <div key={`price-${product.parent_asin}`}>{formatPrice(product.price)}</div>)}<div className="compare-label">Rating</div>{comparedProducts.map((product) => <div key={`rating-${product.parent_asin}`}>{product.average_rating ? `★ ${product.average_rating.toFixed(1)} (${product.rating_number.toLocaleString()})` : "Unavailable"}</div>)}<div className="compare-label">Store</div>{comparedProducts.map((product) => <div key={`store-${product.parent_asin}`}>{product.store ?? "Unavailable"}</div>)}<div className="compare-label">Why it matches</div>{comparedProducts.map((product) => <div key={`reason-${product.parent_asin}`}>{product.match_reasons.join(" · ")}</div>)}<div className="compare-label">Top features</div>{comparedProducts.map((product) => <div key={`features-${product.parent_asin}`}>{product.features.slice(0, 2).join(" · ") || "Unavailable"}</div>)}</div></div></div>}
    </div>
  );
}
