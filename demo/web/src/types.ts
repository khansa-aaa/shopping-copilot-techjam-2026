export type ShoppingMode = "hybrid" | "offline";

export interface Marketplace {
  code: string;
  label: string;
  domain: string;
}

export interface HealthResponse {
  status: "starting" | "ready" | "failed";
  catalog_count: number;
  max_turns: number;
  agent_contract: string;
  hybrid_available: boolean;
  hybrid_model: string;
  startup_seconds: number | null;
  marketplaces: Marketplace[];
}

export interface AgentResponse {
  message: string;
  ask_attribute: string | null;
  recommendations: Array<{ parent_asin: string }>;
  usage: { prompt_tokens: number; completion_tokens: number };
}

export interface Product {
  rank: number;
  parent_asin: string;
  title: string;
  price: number | null;
  store: string | null;
  categories: string[];
  category: string;
  features: string[];
  details: Record<string, string>;
  average_rating: number;
  rating_number: number;
  match_reasons: string[];
  amazon_url: string;
  data_source: "techjam_catalog_snapshot";
  is_live: false;
}

export interface QuickReply {
  label: string;
  message: string;
}

export interface EnhancementState {
  requested: boolean;
  status: string;
  outcome: string;
  enabled: boolean;
  attempted: boolean;
  applied: boolean;
  model: string;
  reasoning_effort: string;
  calls_used: number;
  max_calls: number;
  timeout_seconds: number;
  rank_blend: number;
  latency_ms: number;
  prompt_tokens: number;
  completion_tokens: number;
  used_mode: "hybrid" | "offline" | "offline_fallback";
  fallback_reason: string | null;
}

export interface ExpertState {
  turn: number;
  intent_generation: number;
  route_probabilities: Record<string, number>;
  slots: Record<string, Array<{ value: string; confidence: number; hard: boolean }>>;
  no_preferences: string[];
  profile_priors: string[];
  hard_constraints: string[];
  soft_preferences: string[];
  previously_shown_count: number;
  openai_calls: number;
  next_attribute: string | null;
  latency_ms: number;
  enhancement: EnhancementState;
  retrieval: string[];
}

export interface SessionResponse {
  session_id: string;
  turn: number;
  max_turns: number;
  status: "active" | "complete";
  mode: ShoppingMode;
  marketplace: string;
  expert_state: ExpertState;
}

export interface TurnResponse {
  session_id: string;
  turn: number;
  max_turns: number;
  status: "active" | "complete";
  agent_response: AgentResponse;
  products: Product[];
  experience: {
    quick_replies: QuickReply[];
    snapshot_disclosure: string;
    amazon_disclosure: string;
  };
  expert_state: ExpertState;
  meta: {
    latency_ms: number;
    requested_mode: ShoppingMode;
    used_mode: "hybrid" | "offline" | "offline_fallback";
    fallback_reason: string | null;
    idempotency_replay: boolean;
    estimated_cost_usd: number;
  };
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  turn?: number;
  error?: boolean;
}
