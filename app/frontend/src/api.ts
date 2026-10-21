import type { ApiError, CarbonFactor, DashboardSummary, EnergyOffer, MatchPreview, Participant, Proposal, TradeRecord } from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

export class ApiRequestError extends Error {
  code: string;
  details: Record<string, any>;
  status: number;
  constructor(status: number, error: ApiError["error"]) {
    super(error.message);
    this.status = status;
    this.code = error.code;
    this.details = error.details || {};
  }
}

async function request<T>(path: string, init: RequestInit = {}, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE}/api/v1${path}`, {
    ...init,
    signal,
    headers: { "Content-Type": "application/json", ...(init.headers || {}) },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = (data as ApiError).error || { code: "REQUEST_FAILED", message: "The request could not be completed.", details: {} };
    throw new ApiRequestError(response.status, error);
  }
  return data as T;
}

export const api = {
  health: (signal?: AbortSignal) => request<{ status: string; chain_configured: boolean; chain_connected: boolean; chain_id: number }>("/health", {}, signal),
  participants: (signal?: AbortSignal) => request<Participant[]>("/participants", {}, signal),
  createParticipant: (body: Record<string, unknown>) => request<Participant>("/participants", { method: "POST", body: JSON.stringify(body) }),
  factors: (signal?: AbortSignal) => request<CarbonFactor[]>("/factors", {}, signal),
  offers: (scenario: string, signal?: AbortSignal) => request<EnergyOffer[]>(`/offers?scenario_id=${encodeURIComponent(scenario)}`, {}, signal),
  createOffer: (body: Record<string, unknown>) => request<EnergyOffer>("/offers", { method: "POST", body: JSON.stringify(body) }),
  preview: (scenario_id: string, mode: "carbon_aware" | "price_only", signal?: AbortSignal) => request<MatchPreview>("/matches/preview", { method: "POST", body: JSON.stringify({ scenario_id, mode, score_config_version: "v1" }) }, signal),
  accept: (proposal: Proposal, snapshotVersion: string, idempotencyKey: string) => request<{ trade: TradeRecord; idempotent_replay: boolean }>(`/matches/${encodeURIComponent(proposal.id)}/accept`, {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({ accept_token: proposal.accept_token, snapshot_version: snapshotVersion }),
  }),
  prepareTrade: (trade_id: string) => request<{
    trade_id: string; chain_id: number; contract_address: string;
    contract_payload: Record<string, string | number>; valid_until: number; authorization_signature: string;
  }>("/trades", { method: "POST", body: JSON.stringify({ trade_id }) }),
  registerTransaction: (trade_id: string, transaction_hash: string) => request<TradeRecord>(`/trades/${encodeURIComponent(trade_id)}/transaction`, { method: "POST", body: JSON.stringify({ transaction_hash }) }),
  cancelTrade: (trade_id: string) => request<TradeRecord>(`/trades/${encodeURIComponent(trade_id)}/cancel`, { method: "POST" }),
  trade: (trade_id: string) => request<TradeRecord>(`/trades/${encodeURIComponent(trade_id)}`),
  trades: (scenario: string, signal?: AbortSignal) => request<TradeRecord[]>(`/trades?scenario_id=${encodeURIComponent(scenario)}`, {}, signal),
  dashboard: (scenario: string, signal?: AbortSignal) => request<DashboardSummary>(`/dashboard/summary?scenario_id=${encodeURIComponent(scenario)}`, {}, signal),
  timeseries: (scenario: string, signal?: AbortSignal) => request<Array<{ period: string; energy_wh: number; trade_count: number; emissions_difference_dg: number }>>(`/dashboard/timeseries?scenario_id=${encodeURIComponent(scenario)}`, {}, signal),
};
