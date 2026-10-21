export type OfferSide = "buy" | "sell";
export type TradeStatus = "Offer" | "Pending" | "Done" | "Fail";
export type ComparisonStatus = "comparable" | "baseline_unavailable" | "basis_mismatch";

export interface CarbonFactor {
  id: string;
  value: number;
  value_dg_per_kwh: number;
  unit: "gCO2/kWh" | "gCO2e/kWh";
  region: string;
  data_year: number | null;
  edition_year: number | null;
  demo_scenario: string;
  comparison_basis: { gas: "CO2" | "CO2e"; boundary: "combustion" | "lifecycle" };
  use: "rankable" | "informational";
  provenance: "published" | "fixture" | "simulated" | "convention";
  fixture: boolean;
  simulated: boolean;
  source: { name: string; table?: string | null; row?: string | null };
  factor_hash: string;
}

export interface Participant {
  id: string;
  display_name: string;
  wallet_address: string | null;
  participant_type: "prosumer" | "consumer" | "both";
  region_code: string;
  default_energy_source: string | null;
  default_carbon_factor_id: string | null;
}

export interface EnergyOffer {
  id: string;
  scenario_id: string;
  participant_id: string;
  participant_name: string;
  participant_type: string;
  region_code: string;
  wallet_address: string | null;
  side: OfferSide;
  energy_wh: number;
  reserved_wh: number;
  settled_wh: number;
  available_wh: number;
  price_cents_per_kwh: number;
  currency: "EUR";
  energy_source: string | null;
  carbon_factor_id: string | null;
  carbon_factor: CarbonFactor | null;
  status: "active" | "partially_filled" | "filled" | "cancelled" | "expired";
  expires_at: string;
  created_at: string;
}

export interface Proposal {
  id: string;
  accept_token: string;
  scenario_id: string;
  mode: "carbon_aware" | "price_only";
  request_id: string;
  listing_id: string;
  buyer_id: string;
  seller_id: string;
  buyer_name: string;
  seller_name: string;
  buyer_region: string;
  buyer_address: string;
  seller_address: string;
  matched_energy_wh: number;
  price_cents_per_kwh: number;
  total_cost_cents: number;
  scenario_factor_id: string;
  scenario_factor: CarbonFactor;
  baseline_factor_id: string | null;
  baseline_factor: CarbonFactor | null;
  carbon_comparison_status: ComparisonStatus;
  carbon_diff_dg: number | null;
  estimated_scenario_emissions_dg: number;
  estimated_baseline_emissions_dg: number | null;
  emissions_unit: string;
  declared_year: number;
  carbon_unrated: boolean | null;
  score_total: number;
  score_total_bp: number;
  score_breakdown: { price: number; quantity_fit: number; carbon: number | null; price_bp: number; quantity_fit_bp: number; carbon_bp: number | null };
  weights_configured_bp: Record<string, number>;
  weights_applied_bp: Record<string, number>;
  score_config_version: string;
  score_config_hash: string;
  algorithm_version: string;
  status: "proposed";
  created_at: string;
  expires_at: number;
}

export interface MatchPreview {
  proposals: Proposal[];
  snapshot_version: string;
  scenario_id: string;
  mode: "carbon_aware" | "price_only";
  algorithm_version: string;
  expires_at: number;
}

export interface TradeRecord {
  id: string;
  proposal_id: string;
  scenario_id: string;
  listing_id: string;
  request_id: string;
  buyer_id: string;
  seller_id: string;
  buyer_address: string;
  seller_address: string;
  energy_wh: number;
  price_cents_per_kwh: number;
  total_cost_cents: number;
  scenario_factor_id: string;
  scenario_factor: CarbonFactor;
  baseline_factor_id: string | null;
  baseline_factor: CarbonFactor | null;
  carbon_intensity_dg_per_kwh: number;
  carbon_diff_dg: number | null;
  carbon_comparison_status: ComparisonStatus;
  comparison_basis: { gas: string; boundary: string };
  declared_year: number;
  baseline_factor_hash: string;
  scenario_factor_hash: string;
  score_config_hash: string;
  score_config_version: string;
  mode: string;
  score_total: number;
  valid_until: number;
  authorization_signature: string | null;
  reservation_state: "reserved" | "released" | "settled";
  status: TradeStatus;
  failure_reason: string | null;
  transaction_hash: string | null;
  transaction_from: string | null;
  transaction_nonce: number | null;
  chain_id: number | null;
  block_number: number | null;
  block_timestamp: number | null;
  created_at: string;
  confirmed_at: string | null;
}

export interface DashboardSummary {
  scenario_id: string;
  total_proposed_energy_wh: number;
  energy_traded_wh: number;
  done_trade_count: number;
  renewable_energy_matched_wh: number;
  average_carbon_intensity_g_per_kwh: number | null;
  average_carbon_intensity_dg_per_kwh: number | null;
  average_carbon_intensity_basis: { gas: string; boundary: string };
  excluded_basis_count: number;
  estimated_emissions_difference_dg: number;
  estimated_emissions_difference_kg: number;
  emissions_baseline_factor_id: string;
  emissions_baseline_factor: CarbonFactor | null;
  average_intensity_factors: CarbonFactor[];
  emissions_excluded_match_count: number;
  pending_transaction_count: number;
  failed_transaction_count: number;
  active_buy_request_count: number;
  active_sell_listing_count: number;
  recent_trades: TradeRecord[];
}

export interface ApiError {
  error: { code: string; message: string; details: Record<string, any> };
}
