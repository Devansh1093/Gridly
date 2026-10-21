import { useCallback, useEffect, useMemo, useRef, useState, type Dispatch, type FormEvent, type ReactNode, type SetStateAction } from "react";
import {
  Activity, ArrowLeftRight, ArrowUpRight, BadgeCheck, BatteryCharging,
  Check, ChevronDown, CircleDollarSign, Clock3, Cloud, LayoutDashboard, Leaf,
  Loader2, MapPin, Plus, RefreshCcw, ShieldCheck, SlidersHorizontal,
  Sparkles, Sun, Wallet, Wind, X, Zap,
} from "lucide-react";
import { api, ApiRequestError } from "./api";
import { comparisonLabel, formatEuroCents, formatEuroCentsPerKwh, formatFactor, formatKgFromDg, formatKwh, formatNumber, formatScore, parseEuroToCents, parseKwhToWh, statusLabel } from "./format";
import type { CarbonFactor, DashboardSummary, EnergyOffer, MatchPreview, Participant, Proposal, TradeRecord } from "./types";

type Section = "dashboard" | "marketplace" | "matches" | "activity";
type Scenario = "sunny-day" | "low-generation" | "demand-spike";
type Mode = "carbon_aware" | "price_only";
type OfferFormState = { side: "buy" | "sell"; participant_id: string; energy_kwh: string; price_eur: string; source: string; scenario_id: Scenario; expires_at: string };
type EthereumProvider = { request: (args: { method: string; params?: unknown[] }) => Promise<any> };
declare global { interface Window { ethereum?: EthereumProvider } }

const SCENARIOS: Array<{ id: Scenario; label: string; note: string }> = [
  { id: "sunny-day", label: "Sunny day", note: "Renewable surplus" },
  { id: "low-generation", label: "Low generation", note: "Limited renewable supply" },
  { id: "demand-spike", label: "Demand spike", note: "Higher demand" },
];
const STATUS_CLASS: Record<string, string> = { Offer: "status offer", Pending: "status pending", Done: "status done", Fail: "status fail" };
function chainName(chainId: number) { return chainId === 11155111 ? "Sepolia" : chainId === 31337 ? "Hardhat Local" : `EVM network ${chainId}`; }

function initials(name: string) { return name.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase(); }
function shortHash(hash: string | null | undefined) { return hash ? `${hash.slice(0, 9)}…${hash.slice(-7)}` : "Not submitted"; }
function plusDays(days: number) { const date = new Date(Date.now() + days * 86400000); const pad = (value: number) => String(value).padStart(2, "0"); return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`; }
function errorText(error: unknown) { return error instanceof Error ? error.message : "Something went wrong. Please try again."; }

function FactorBadge({ factor }: { factor?: CarbonFactor | null }) {
  if (!factor) return <span className="badge badge-neutral">Factor unavailable</span>;
  return factor.simulated ? <span className="badge badge-warn"><Cloud size={12} /> Simulated data</span> : <span className="badge badge-neutral">Published data</span>;
}

function StatusBadge({ status }: { status: string }) {
  const Icon = status === "Done" ? BadgeCheck : status === "Pending" ? Clock3 : status === "Fail" ? X : Wallet;
  return <span className={STATUS_CLASS[status] || "status proposed"}><Icon size={13} />{statusLabel(status)}</span>;
}

function PageTitle({ eyebrow, title, subtitle }: { eyebrow: string; title: string; subtitle: string }) {
  const [first, ...rest] = title.split(" ");
  return <div className="page-title"><p className="section-label">{eyebrow}</p><h1><span>{first} </span><strong>{rest.join(" ")}</strong></h1><p className="page-subtitle">{subtitle}</p></div>;
}

function CubeDecoration() {
  return <div className="cube-decoration" aria-hidden="true"><span /><span /><span /></div>;
}

export default function App() {
  const [section, setSection] = useState<Section>("dashboard");
  const [scenario, setScenario] = useState<Scenario>("sunny-day");
  const [aggregate, setAggregate] = useState(false);
  const [participants, setParticipants] = useState<Participant[]>([]);
  const [factors, setFactors] = useState<CarbonFactor[]>([]);
  const [offers, setOffers] = useState<EnergyOffer[]>([]);
  const [trades, setTrades] = useState<TradeRecord[]>([]);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [series, setSeries] = useState<Array<{ period: string; energy_wh: number; trade_count: number; emissions_difference_dg: number }>>([]);
  const [loading, setLoading] = useState(true);
  const [pageError, setPageError] = useState("");
  const [apiReady, setApiReady] = useState(false);
  const [chainReady, setChainReady] = useState(false);
  const [chainConfigured, setChainConfigured] = useState(false);
  const [mode, setMode] = useState<Mode>("carbon_aware");
  const [previews, setPreviews] = useState<Partial<Record<Mode, MatchPreview>>>({});
  const [matching, setMatching] = useState(false);
  const [acceptingId, setAcceptingId] = useState("");
  const [submittingId, setSubmittingId] = useState("");
  const [activeTrade, setActiveTrade] = useState<TradeRecord | null>(null);
  const [walletAddress, setWalletAddress] = useState("");
  const [walletError, setWalletError] = useState("");
  const [marketSide, setMarketSide] = useState<"all" | "buy" | "sell">("all");
  const [marketSource, setMarketSource] = useState("all");
  const [maxPrice, setMaxPrice] = useState("");
  const [maxCarbon, setMaxCarbon] = useState("");
  const [minimumQuantity, setMinimumQuantity] = useState("");
  const [offerMessage, setOfferMessage] = useState("");
  const [offerError, setOfferError] = useState("");
  const [offerSaving, setOfferSaving] = useState(false);
  const [offerForm, setOfferForm] = useState<OfferFormState>({ side: "sell", participant_id: "P1", energy_kwh: "100", price_eur: "0.10", source: "solar", scenario_id: "sunny-day", expires_at: plusDays(7) });
  const acceptKeys = useRef(new Map<string, string>());

  const refresh = useCallback(async (nextScenario: Scenario = scenario, signal?: AbortSignal) => {
    setLoading(true);
    setPageError("");
    try {
      const scope = aggregate ? "all" : nextScenario;
      const [health, nextOffers, nextTrades, nextSummary, nextSeries] = await Promise.all([
        api.health(signal), api.offers(nextScenario, signal), api.trades(scope, signal), api.dashboard(scope, signal), api.timeseries(scope, signal),
      ]);
      setApiReady(true);
      setChainReady(health.chain_connected);
      setChainConfigured(health.chain_configured);
      setOffers(nextOffers);
      setTrades(nextTrades);
      setSummary(nextSummary);
      setSeries(nextSeries);
    } catch (error) {
      if (signal?.aborted) return;
      setPageError(errorText(error));
      setApiReady(false);
    } finally { if (!signal?.aborted) setLoading(false); }
  }, [scenario, aggregate]);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([api.participants(controller.signal), api.factors(controller.signal)]).then(([people, factorRows]) => {
      setParticipants(people); setFactors(factorRows);
    }).catch((error) => { if (!controller.signal.aborted) setPageError(errorText(error)); });
    void refresh(scenario, controller.signal);
    return () => controller.abort();
  }, [scenario, aggregate, refresh]);

  const activePreview = previews[mode];
  const visibleOffers = useMemo(() => offers.filter((offer) => {
    if (marketSide !== "all" && offer.side !== marketSide) return false;
    if (marketSource !== "all" && offer.energy_source !== marketSource) return false;
    if (maxPrice) { try { if (offer.price_cents_per_kwh > parseEuroToCents(maxPrice)) return false; } catch { return false; } }
    if (minimumQuantity) { try { if (offer.available_wh < parseKwhToWh(minimumQuantity)) return false; } catch { return false; } }
    if (maxCarbon && offer.side === "sell" && (!offer.carbon_factor || offer.carbon_factor.value > Number(maxCarbon))) return false;
    return offer.status === "active" || offer.status === "partially_filled";
  }), [offers, marketSide, marketSource, maxPrice, minimumQuantity, maxCarbon]);

  const runMatching = async () => {
    setMatching(true); setWalletError(""); setPreviews({});
    try {
      const [carbon, price] = await Promise.all([
        api.preview(scenario, "carbon_aware"), api.preview(scenario, "price_only"),
      ]);
      setPreviews({ carbon_aware: carbon, price_only: price });
    } catch (error) { setWalletError(errorText(error)); }
    finally { setMatching(false); }
  };

  const acceptProposal = async (proposal: Proposal, preview: MatchPreview) => {
    setAcceptingId(proposal.id); setWalletError("");
    const keyId = `${preview.snapshot_version}:${proposal.id}:${proposal.accept_token}`;
    const storageId = `gridly:idempotency:${keyId}`;
    let key = acceptKeys.current.get(keyId) || sessionStorage.getItem(storageId) || undefined;
    if (!key) {
      key = `accept-${crypto.randomUUID()}`;
      acceptKeys.current.set(keyId, key);
      sessionStorage.setItem(storageId, key);
    }
    try {
      const result = await api.accept(proposal, preview.snapshot_version, key);
      setActiveTrade(result.trade);
      await refresh(scenario);
    } catch (error) {
      if (error instanceof ApiRequestError && error.code === "stale_preview") {
        const fresh = error.details.fresh_preview as MatchPreview | undefined;
        if (fresh) setPreviews((current) => ({ ...current, [fresh.mode]: fresh }));
        acceptKeys.current.delete(keyId);
        sessionStorage.removeItem(storageId);
        setWalletError("The market changed since this preview. Review the refreshed proposal and accept it again.");
      } else setWalletError(errorText(error));
    } finally { setAcceptingId(""); }
  };

  const submitToWallet = async (trade: TradeRecord) => {
    setSubmittingId(trade.id); setWalletError("");
    try {
      if (!window.ethereum) throw new Error("No browser wallet found. Install a wallet such as MetaMask and connect it to the configured test network.");
      const [{ BrowserProvider, Contract, toBeHex }, registryArtifact] = await Promise.all([
        import("ethers"), import("../../contracts/abi/TradeRegistry.json"),
      ]);
      const prepared = await api.prepareTrade(trade.id);
      const desiredChain = prepared.chain_id;
      let provider = new BrowserProvider(window.ethereum as any);
      let network = await provider.getNetwork();
      if (Number(network.chainId) !== desiredChain) {
        try {
          await window.ethereum.request({ method: "wallet_switchEthereumChain", params: [{ chainId: toBeHex(desiredChain) }] });
        } catch (switchError: any) {
          if (switchError?.code === 4902) {
            await window.ethereum.request({ method: "wallet_addEthereumChain", params: [{
              chainId: toBeHex(desiredChain), chainName: chainName(desiredChain), rpcUrls: [import.meta.env.VITE_RPC_URL || "http://127.0.0.1:8545"],
              nativeCurrency: { name: desiredChain === 11155111 ? "Sepolia Ether" : "Test Ether", symbol: "ETH", decimals: 18 },
            }] });
          } else throw new Error(`Switch your wallet to ${chainName(desiredChain)} (chain ${desiredChain}) and try again.`);
        }
        provider = new BrowserProvider(window.ethereum as any);
        network = await provider.getNetwork();
      }
      if (Number(network.chainId) !== desiredChain) throw new Error(`Wallet is on chain ${network.chainId}; the trade requires chain ${desiredChain}.`);
      const signer = await provider.getSigner();
      const address = await signer.getAddress();
      setWalletAddress(address);
      const registry = new Contract(prepared.contract_address, registryArtifact.abi as any, signer);
      const tx = await registry.getFunction("recordTrade")(prepared.contract_payload, prepared.authorization_signature);
      const registered = await api.registerTransaction(trade.id, tx.hash);
      setActiveTrade(registered);
      await refresh(scenario);
      try { await tx.wait(); } catch { /* The API reconciler decides whether a mined transaction succeeded. */ }
      for (let attempt = 0; attempt < 22; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 3000));
        const updated = await api.trade(trade.id);
        setActiveTrade(updated);
        if (updated.status === "Done" || updated.status === "Fail") break;
      }
      await refresh(scenario);
    } catch (error: any) {
      if (error?.code === 4001) {
        try { const failed = await api.cancelTrade?.(trade.id); if (failed) setActiveTrade(failed as TradeRecord); } catch { /* The reservation remains held until its signed deadline is safe. */ }
        setWalletError("Wallet signing was rejected. The reservation will remain held until its authorization expires and reconciliation confirms it was not recorded.");
      } else {
        setWalletError(errorText(error));
      }
    } finally { setSubmittingId(""); }
  };

  const saveOffer = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setOfferError(""); setOfferMessage(""); setOfferSaving(true);
    try {
      const energy_wh = parseKwhToWh(offerForm.energy_kwh);
      const price_cents_per_kwh = parseEuroToCents(offerForm.price_eur);
      const payload = {
        side: offerForm.side, participant_id: offerForm.participant_id, scenario_id: offerForm.scenario_id,
        energy_wh, price_cents_per_kwh, currency: "EUR", expires_at: new Date(offerForm.expires_at).toISOString(),
        ...(offerForm.side === "sell" ? { energy_source: offerForm.source, carbon_factor_id: offerForm.source === "solar" ? "solar_direct_co2" : offerForm.source === "wind" ? "wind_direct_co2" : "grid_tr_iea2025" } : {}),
      };
      await api.createOffer(payload);
      setScenario(offerForm.scenario_id);
      setOfferMessage("Your demo listing was added to the selected scenario.");
      await refresh(offerForm.scenario_id);
    } catch (error) { setOfferError(errorText(error)); }
    finally { setOfferSaving(false); }
  };

  const registerParticipant = async (body: Record<string, unknown>) => {
    const participant = await api.createParticipant(body);
    setParticipants((rows) => [...rows, participant].sort((a, b) => a.id.localeCompare(b.id)));
    return participant;
  };

  const connectWallet = async () => {
    setWalletError("");
    try {
      if (!window.ethereum) throw new Error("No browser wallet found. Install MetaMask to connect a demo account.");
      const { BrowserProvider } = await import("ethers");
      const provider = new BrowserProvider(window.ethereum as any);
      const accounts = await provider.send("eth_requestAccounts", []);
      setWalletAddress(accounts[0] || "");
    } catch (error) { setWalletError(errorText(error)); }
  };

  const updateScenario = (value: Scenario) => {
    setScenario(value); setPreviews({}); setActiveTrade(null); setAggregate(false);
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <button className="brand-lockup" onClick={() => setSection("dashboard")} aria-label="Gridly dashboard">
          <span className="brand-mark"><Zap size={21} fill="currentColor" /></span><span><b>gridly</b><small>community energy</small></span>
        </button>
        <div className="side-label">Workspace</div>
        <nav className="main-nav" aria-label="Main navigation">
          <NavItem icon={<LayoutDashboard size={18} />} label="Dashboard" active={section === "dashboard"} onClick={() => setSection("dashboard")} />
          <NavItem icon={<ArrowLeftRight size={18} />} label="Marketplace" active={section === "marketplace"} onClick={() => { setAggregate(false); setSection("marketplace"); }} />
          <NavItem icon={<Sparkles size={18} />} label="Match center" active={section === "matches"} onClick={() => { setAggregate(false); setSection("matches"); }} />
          <NavItem icon={<Activity size={18} />} label="Trade activity" active={section === "activity"} onClick={() => { setAggregate(false); setSection("activity"); }} />
        </nav>
        <div className="sidebar-spacer" />
        <div className="network-card">
          <span className={`network-dot ${chainReady ? "online" : ""}`} />
          <div><strong>{chainReady ? `${chainName(Number(import.meta.env.VITE_CHAIN_ID || 31337))} connected` : chainConfigured ? "Contract configured" : "Contract not deployed"}</strong><small>{chainReady ? `Chain ${import.meta.env.VITE_CHAIN_ID || 31337}` : chainConfigured ? "Check the API chain connection" : "Deploy the contract to configure wallet trades"}</small></div>
          {chainReady ? <ShieldCheck size={17} /> : <CircleHelpIcon />}
        </div>
        <div className="sidebar-footer">P2P energy marketplace <span>Demo environment</span></div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div className="mobile-brand"><span className="brand-mark"><Zap size={18} fill="currentColor" /></span><b>gridly</b></div>
          <div className="breadcrumb"><span>Workspace</span><ChevronDown size={13} /><strong>{section === "activity" ? "Trade activity" : section === "matches" ? "Match center" : section[0].toUpperCase() + section.slice(1)}</strong></div>
          <div className="topbar-actions">
            <label className="scenario-picker"><Sun size={15} /><select value={scenario} onChange={(event) => updateScenario(event.target.value as Scenario)} aria-label="Demo scenario">
              {SCENARIOS.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
            </select><ChevronDown size={13} /></label>
            <button className={`wallet-button ${walletAddress ? "connected" : ""}`} onClick={walletAddress ? undefined : connectWallet} title={walletAddress || "Connect a browser wallet"}>
              <Wallet size={16} />{walletAddress ? `${walletAddress.slice(0, 6)}…${walletAddress.slice(-4)}` : "Connect wallet"}
            </button>
          </div>
        </header>
        <nav className="mobile-nav" aria-label="Main navigation">
          <button className={section === "dashboard" ? "active" : ""} onClick={() => setSection("dashboard")}><LayoutDashboard size={16} /><span>Home</span></button>
          <button className={section === "marketplace" ? "active" : ""} onClick={() => { setAggregate(false); setSection("marketplace"); }}><ArrowLeftRight size={16} /><span>Market</span></button>
          <button className={section === "matches" ? "active" : ""} onClick={() => { setAggregate(false); setSection("matches"); }}><Sparkles size={16} /><span>Match</span></button>
          <button className={section === "activity" ? "active" : ""} onClick={() => { setAggregate(false); setSection("activity"); }}><Activity size={16} /><span>Activity</span></button>
        </nav>

        {!apiReady && pageError && <div className="service-banner error-banner"><X size={18} /><div><b>API unavailable</b><span>{pageError} Start the backend with the project setup instructions.</span></div></div>}
        {walletError && <div className="service-banner error-banner"><X size={18} /><div><b>Action needs attention</b><span>{walletError}</span></div><button onClick={() => setWalletError("")} aria-label="Dismiss"><X size={16} /></button></div>}

        {section === "dashboard" && <DashboardView
          loading={loading} summary={summary} offers={offers} trades={trades} series={series} scenario={scenario}
          aggregate={aggregate} setAggregate={setAggregate} setSection={setSection} onRefresh={() => refresh(scenario)}
          previews={previews} onCompare={runMatching} matching={matching} setMode={setMode} mode={mode} setPreviews={setPreviews}
        />}
        {section === "marketplace" && <MarketplaceView
          scenario={scenario} offers={visibleOffers} allOffers={offers} loading={loading} marketSide={marketSide} setMarketSide={setMarketSide}
          marketSource={marketSource} setMarketSource={setMarketSource} maxPrice={maxPrice} setMaxPrice={setMaxPrice}
          minimumQuantity={minimumQuantity} setMinimumQuantity={setMinimumQuantity} maxCarbon={maxCarbon} setMaxCarbon={setMaxCarbon} participants={participants} factors={factors}
          offerForm={offerForm} setOfferForm={setOfferForm} onSubmit={saveOffer} saving={offerSaving} message={offerMessage} error={offerError} onCreateParticipant={registerParticipant}
        />}
        {section === "matches" && <MatchCenterView
          scenario={scenario} mode={mode} setMode={setMode} previews={previews} activePreview={activePreview}
          matching={matching} onRun={runMatching} onAccept={acceptProposal} acceptingId={acceptingId}
          activeTrade={activeTrade} onSubmitTrade={submitToWallet} submittingId={submittingId}
        />}
        {section === "activity" && <ActivityView trades={trades} activeTrade={activeTrade} onSubmitTrade={submitToWallet} submittingId={submittingId} onReload={() => refresh(scenario)} />}
      </main>
    </div>
  );
}

function CircleHelpIcon() { return <span className="help-mark">i</span>; }

function NavItem({ icon, label, active, onClick }: { icon: ReactNode; label: string; active: boolean; onClick: () => void }) {
  return <button className={`nav-item ${active ? "active" : ""}`} onClick={onClick}>{icon}<span>{label}</span>{active && <i />}</button>;
}

function DashboardView(props: {
  loading: boolean; summary: DashboardSummary | null; offers: EnergyOffer[]; trades: TradeRecord[];
  series: Array<{ period: string; energy_wh: number; trade_count: number; emissions_difference_dg: number }>;
  scenario: Scenario; aggregate: boolean; setAggregate: (value: boolean) => void; setSection: (section: Section) => void;
  onRefresh: () => void; previews: Partial<Record<Mode, MatchPreview>>; onCompare: () => void; matching: boolean;
  setMode: (mode: Mode) => void; mode: Mode; setPreviews: Dispatch<SetStateAction<Partial<Record<Mode, MatchPreview>>>>;
}) {
  const { summary, series, scenario } = props;
  const scenarioInfo = SCENARIOS.find((item) => item.id === scenario)!;
  const totalCarbon = (preview?: MatchPreview) => preview?.proposals.reduce((sum, proposal) => sum + (proposal.carbon_diff_dg || 0), 0) || 0;
  const previewEnergy = (preview?: MatchPreview) => preview?.proposals.reduce((sum, proposal) => sum + proposal.matched_energy_wh, 0) || 0;
  return <div className="page-wrap">
    <div className="hero-row">
      <div><p className="hero-eyebrow">Trade clean energy in minutes</p><h1 className="hero-title"><span>Better energy,</span><strong>together.</strong></h1>
        <p className="hero-copy">A transparent peer-to-peer market for local energy. Compare price and carbon before a trade is recorded.</p>
        <div className="hero-actions"><button className="button primary" onClick={() => props.setSection("matches")}><Sparkles size={16} /> Explore matches</button><button className="button secondary" onClick={() => props.setSection("marketplace")}><ArrowLeftRight size={16} /> Browse market</button></div>
      </div>
      <div className="hero-art"><CubeDecoration /><div className="art-card"><span className="art-icon"><Leaf size={18} /></span><span><b>Energy, with context.</b><small>Every estimate shows its source.</small></span><ArrowUpRight size={16} /></div><div className="floating-tag"><span /> LOCAL · TRANSPARENT</div></div>
    </div>

    <div className="section-heading-row"><div><p className="section-label">Your overview</p><h2>Market at a glance</h2></div><div className="heading-actions"><button className={`segmented ${props.aggregate ? "selected" : ""}`} onClick={() => props.setAggregate(!props.aggregate)} title="All scenarios is an aggregate dashboard view only">{props.aggregate ? "All scenarios" : scenarioInfo.label}</button><button className="icon-button" aria-label="Refresh dashboard" onClick={props.onRefresh}><RefreshCcw size={16} /></button></div></div>
    {props.aggregate && <p className="inline-note"><Activity size={14} /> Aggregate metrics include all isolated scenarios; matching still runs one scenario at a time.</p>}
    {props.loading ? <LoadingState label="Loading demo market…" /> : !summary ? <EmptyState title="Dashboard is waiting" detail="The API has not returned market metrics yet." /> : <>
      <div className="metric-grid">
        <MetricCard icon={<BatteryCharging size={18} />} label="Energy traded" value={formatKwh(summary.energy_traded_wh)} foot={`${formatNumber(summary.done_trade_count)} completed trades`} accent="blue" />
        <MetricCard icon={<Leaf size={18} />} label="Renewable matched" value={formatKwh(summary.renewable_energy_matched_wh)} foot="Solar and wind trade volume" />
        <MetricCard icon={<Cloud size={18} />} label="Est. emissions difference" value={formatKgFromDg(summary.estimated_emissions_difference_dg, "CO₂")} foot={<><span>vs. {summary.emissions_baseline_factor_id} · {summary.emissions_excluded_match_count} excluded · {summary.emissions_baseline_factor?.source.name}</span><FactorBadge factor={summary.emissions_baseline_factor} /></>} />
        <MetricCard icon={<Wind size={18} />} label="Avg. carbon intensity" value={summary.average_carbon_intensity_g_per_kwh == null ? "—" : `${formatNumber(summary.average_carbon_intensity_g_per_kwh, 1)} gCO₂/kWh`} foot={summary.average_carbon_intensity_g_per_kwh == null ? "No completed trades" : <><span>CO₂, combustion · {summary.excluded_basis_count} outside basis</span>{summary.average_intensity_factors.map((factor) => <FactorBadge key={factor.id} factor={factor} />)}</>} />
      </div>
      <div className="panel-grid dashboard-panels">
        <section className="panel chart-panel"><div className="panel-heading"><div><p className="section-label">Trade activity</p><h3>Energy over time</h3></div><span className="unit-caption">kWh · completed trades</span></div>
          {series.length === 0 ? <div className="chart-empty"><Activity size={20} /><span>No completed trades yet</span><small>The chart fills after the backend confirms a trade.</small></div> : <div className="bar-chart" role="img" aria-label="Completed energy traded over time">
            {series.map((point) => { const max = Math.max(...series.map((row) => row.energy_wh), 1); return <div key={point.period} className="bar-column"><span className="bar-value">{formatNumber(point.energy_wh / 1000, 1)}</span><div className="bar-track"><i style={{ height: `${Math.max(8, point.energy_wh / max * 100)}%` }} /></div><span className="bar-label">{point.period}</span></div>; })}
          </div>}
          <div className="chart-foot"><span><i className="legend-dot" /> Confirmed on chain</span><span>Units are kWh</span></div>
        </section>
        <section className="panel compare-panel"><div className="panel-heading"><div><p className="section-label">Matching modes</p><h3>Carbon-aware vs price-only</h3></div><button className="text-button" onClick={() => { props.setSection("matches"); props.setMode("carbon_aware"); if (!props.previews.carbon_aware) props.onCompare(); }}>Compare <ArrowUpRight size={14} /></button></div>
          <p className="panel-description">See how the score changes across the same isolated scenario fixtures.</p>
          {props.previews.carbon_aware && props.previews.price_only ? <div className="comparison-pair">
            <CompareModeCard mode="carbon_aware" preview={props.previews.carbon_aware} carbon={totalCarbon(props.previews.carbon_aware)} energy={previewEnergy(props.previews.carbon_aware)} />
            <CompareModeCard mode="price_only" preview={props.previews.price_only} carbon={totalCarbon(props.previews.price_only)} energy={previewEnergy(props.previews.price_only)} />
          </div> : <div className="comparison-placeholder"><div className="compare-icons"><span><Leaf size={16} /></span><ArrowLeftRight size={15} /><span><CircleDollarSign size={16} /></span></div><span>Run both ranking modes against the same scenario.</span><button className="button outline-small" disabled={props.matching} onClick={props.onCompare}>{props.matching ? <Loader2 className="spin" size={14} /> : <Sparkles size={14} />}{props.matching ? "Comparing…" : "Run comparison"}</button></div>}
        </section>
      </div>
      <div className="panel recent-panel"><div className="panel-heading"><div><p className="section-label">Latest activity</p><h3>Recent trades</h3></div><button className="text-button" onClick={() => props.setSection("activity")}>View activity <ArrowUpRight size={14} /></button></div>
        {summary.recent_trades.length === 0 ? <EmptyState title="No trades yet" detail="Accept a proposal and submit it from a connected local wallet." compact /> : <div className="table-wrap"><table><thead><tr><th>Trade</th><th>Participants</th><th className="right">Energy</th><th>Status</th><th>Transaction</th></tr></thead><tbody>{summary.recent_trades.slice(0, 4).map((trade) => <TradeRow key={trade.id} trade={trade} />)}</tbody></table></div>}
      </div>
    </>}
  </div>;
}

function MetricCard({ icon, label, value, foot, accent = "" }: { icon: ReactNode; label: string; value: string; foot: ReactNode; accent?: string }) {
  return <article className={`metric-card ${accent}`}><div className="metric-top"><span className="metric-icon">{icon}</span><span className="metric-label">{label}</span></div><strong className="metric-value">{value}</strong><div className="metric-foot">{foot}</div></article>;
}

function CompareModeCard({ mode, preview, carbon, energy }: { mode: Mode; preview: MatchPreview; carbon: number; energy: number }) {
  const title = mode === "carbon_aware" ? "Carbon-aware" : "Price-only";
  const icon = mode === "carbon_aware" ? <Leaf size={15} /> : <CircleDollarSign size={15} />;
  const top = preview.proposals[0];
  return <div className={`mode-result ${mode}`}><div className="mode-result-head">{icon}<b>{title}</b><span>{preview.proposals.length} fills</span></div><div className="mode-winner">{top ? <><small>First selected</small><strong>{top.seller_name}</strong><span>{formatEuroCentsPerKwh(top.price_cents_per_kwh)} · {formatKwh(top.matched_energy_wh)}</span></> : <><small>No eligible fills</small><strong>—</strong><span>Check request limits</span></>}</div><div className="mode-stats"><span><b>{formatKwh(energy)}</b><small>proposed</small></span><span><b>{formatKgFromDg(carbon)}</b><small>est. difference</small></span></div></div>;
}

function MarketplaceView(props: {
  scenario: Scenario; offers: EnergyOffer[]; allOffers: EnergyOffer[]; loading: boolean; marketSide: "all" | "buy" | "sell"; setMarketSide: (v: "all" | "buy" | "sell") => void;
  marketSource: string; setMarketSource: (v: string) => void; maxPrice: string; setMaxPrice: (v: string) => void; minimumQuantity: string; setMinimumQuantity: (v: string) => void; maxCarbon: string; setMaxCarbon: (v: string) => void;
  participants: Participant[]; factors: CarbonFactor[]; offerForm: OfferFormState;
  setOfferForm: Dispatch<SetStateAction<OfferFormState>>; onSubmit: (event: FormEvent<HTMLFormElement>) => void; saving: boolean; message: string; error: string;
  onCreateParticipant: (body: Record<string, unknown>) => Promise<Participant>;
}) {
  const { offerForm, setOfferForm, participants } = props;
  const [profileOpen, setProfileOpen] = useState(false);
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileError, setProfileError] = useState("");
  const [profileMessage, setProfileMessage] = useState("");
  const [profileForm, setProfileForm] = useState({ display_name: "", participant_type: "prosumer" as "prosumer" | "consumer" | "both", region_code: "TR", wallet_address: "", default_energy_source: "solar" });
  const sourceNames = [...new Set(props.allOffers.map((offer) => offer.energy_source).filter((value): value is string => Boolean(value)))];
  const sellablePeople = participants.filter((person) => person.participant_type !== "consumer");
  const buyablePeople = participants.filter((person) => person.participant_type !== "prosumer");
  const currentPeople = offerForm.side === "sell" ? sellablePeople : buyablePeople;
  const set = (key: keyof typeof offerForm, value: string) => setOfferForm((old) => ({ ...old, [key]: value }));
  const preview = (() => { try { return `${formatKwh(parseKwhToWh(offerForm.energy_kwh))} · ${formatEuroCentsPerKwh(parseEuroToCents(offerForm.price_eur))}`; } catch { return "Enter a valid quantity and price"; } })();
  const saveProfile = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setProfileError(""); setProfileMessage(""); setProfileSaving(true);
    try {
      const created = await props.onCreateParticipant({ ...profileForm, wallet_address: profileForm.wallet_address || null, default_energy_source: profileForm.participant_type === "consumer" ? null : profileForm.default_energy_source });
      setProfileMessage(`${created.display_name} is ready to publish listings.`);
      const allowed = offerForm.side === "sell" ? created.participant_type !== "consumer" : created.participant_type !== "prosumer";
      if (allowed) setOfferForm((old) => ({ ...old, participant_id: created.id }));
      setProfileForm((old) => ({ ...old, display_name: "", wallet_address: "" }));
    } catch (error) { setProfileError(errorText(error)); }
    finally { setProfileSaving(false); }
  };
  return <div className="page-wrap">
    <PageTitle eyebrow="Open market" title="Energy marketplace" subtitle="Explore demo sell listings and buy requests. Listings remain scoped to the selected scenario." />
    <div className="market-toolbar"><div className="tabs"><button className={props.marketSide === "all" ? "active" : ""} onClick={() => props.setMarketSide("all")}>All listings</button><button className={props.marketSide === "buy" ? "active" : ""} onClick={() => props.setMarketSide("buy")}>Buy requests</button><button className={props.marketSide === "sell" ? "active" : ""} onClick={() => props.setMarketSide("sell")}>Sell listings</button></div><div className="toolbar-tag"><MapPin size={13} />{SCENARIOS.find((row) => row.id === props.scenario)?.label}</div></div>
    <div className="market-layout">
      <section className="market-listing-area"><div className="filter-strip"><span><SlidersHorizontal size={15} /> Filters</span><label><small>Max price (EUR / kWh)</small><input type="number" min="0" step="0.01" placeholder="Any" value={props.maxPrice} onChange={(e) => props.setMaxPrice(e.target.value)} /></label><label><small>Min. available (kWh)</small><input type="number" min="0" step="1" placeholder="Any" value={props.minimumQuantity} onChange={(e) => props.setMinimumQuantity(e.target.value)} /></label><label><small>Max intensity (gCO₂/kWh)</small><input type="number" min="0" step="0.1" placeholder="Any" value={props.maxCarbon} onChange={(e) => props.setMaxCarbon(e.target.value)} /></label><label><small>Source</small><select value={props.marketSource} onChange={(e) => props.setMarketSource(e.target.value)}><option value="all">Any source</option>{sourceNames.map((source) => <option key={source}>{source}</option>)}</select></label></div>
        <div className="market-card-list">{props.loading ? <LoadingState label="Loading listings…" /> : props.offers.length === 0 ? <EmptyState title="No listings match" detail="Adjust filters or choose another demo scenario." /> : props.offers.map((offer) => <OfferCard key={offer.id} offer={offer} />)}</div>
      </section>
      <section className="panel publish-panel"><div className="panel-heading"><div><p className="section-label">Participate</p><h3>Publish a listing</h3></div><span className="publish-icon"><Plus size={17} /></span></div><p className="panel-description">Create a buy request or a sell listing in the active demo scenario.</p>
        <button type="button" className="text-button profile-toggle" onClick={() => setProfileOpen(!profileOpen)}><Plus size={13} />Register a demo energy profile</button>
        {profileMessage && <div className="form-alert success-alert"><Check size={14} />{profileMessage}</div>}{profileError && <div className="form-alert error-alert"><X size={14} />{profileError}</div>}
        {profileOpen && <form className="profile-form" onSubmit={saveProfile}><label>Display name<input required minLength={2} maxLength={160} value={profileForm.display_name} onChange={(e) => setProfileForm((old) => ({ ...old, display_name: e.target.value }))} placeholder="Community solar co-op" /></label><div className="two-fields"><label>Role<select value={profileForm.participant_type} onChange={(e) => setProfileForm((old) => ({ ...old, participant_type: e.target.value as typeof old.participant_type }))}><option value="prosumer">Prosumer</option><option value="consumer">Consumer</option><option value="both">Both</option></select></label><label>Region<input required minLength={2} maxLength={8} value={profileForm.region_code} onChange={(e) => setProfileForm((old) => ({ ...old, region_code: e.target.value.toUpperCase() }))} /></label></div>{profileForm.participant_type !== "consumer" && <label>Default source<select value={profileForm.default_energy_source} onChange={(e) => setProfileForm((old) => ({ ...old, default_energy_source: e.target.value }))}><option value="solar">Solar</option><option value="wind">Wind</option><option value="grid_mix">Grid mix</option></select></label>}<label>Wallet address (optional)<input value={profileForm.wallet_address} onChange={(e) => setProfileForm((old) => ({ ...old, wallet_address: e.target.value }))} placeholder="0x…" /></label><button className="button secondary full" disabled={profileSaving}>{profileSaving ? <Loader2 className="spin" size={14} /> : <Check size={14} />}{profileSaving ? "Saving profile…" : "Create profile"}</button></form>}
        {props.message && <div className="form-alert success-alert"><Check size={14} />{props.message}</div>}{props.error && <div className="form-alert error-alert"><X size={14} />{props.error}</div>}
        <form className="form-stack" onSubmit={props.onSubmit}>
          <label>Listing type<select value={offerForm.side} onChange={(e) => { const side = e.target.value as "buy" | "sell"; const allowed = side === "sell" ? sellablePeople : buyablePeople; setOfferForm((old) => ({ ...old, side, participant_id: allowed[0]?.id || "" })); }}><option value="sell">Sell listing</option><option value="buy">Buy request</option></select></label>
          <label>Participant<select required value={offerForm.participant_id} onChange={(e) => set("participant_id", e.target.value)}>{currentPeople.map((person) => <option value={person.id} key={person.id}>{person.display_name} · {person.region_code}</option>)}</select></label>
          <div className="two-fields"><label>Energy (kWh)<input required inputMode="decimal" value={offerForm.energy_kwh} onChange={(e) => set("energy_kwh", e.target.value)} placeholder="100" /></label><label>Price (EUR / kWh)<input required inputMode="decimal" value={offerForm.price_eur} onChange={(e) => set("price_eur", e.target.value)} placeholder="0.10" /></label></div>
          {offerForm.side === "sell" && <label>Energy source<select value={offerForm.source} onChange={(e) => set("source", e.target.value)}><option value="solar">Solar</option><option value="wind">Wind</option><option value="grid_mix">Grid mix</option></select></label>}
          <label>Scenario<select value={offerForm.scenario_id} onChange={(e) => set("scenario_id", e.target.value)}>{SCENARIOS.map((row) => <option key={row.id} value={row.id}>{row.label}</option>)}</select></label>
          <label>Expires at<input required type="datetime-local" value={offerForm.expires_at} onChange={(e) => set("expires_at", e.target.value)} /></label>
          <div className="normalized-preview"><span>Normalized values</span><strong>{preview}</strong><small>Quantity is stored as integer Wh; price is integer euro cents/kWh.</small></div>
          <button className="button primary full" disabled={props.saving || !currentPeople.length}>{props.saving ? <Loader2 className="spin" size={16} /> : <Plus size={16} />}{props.saving ? "Publishing…" : "Publish listing"}</button>
        </form>
      </section>
    </div>
  </div>;
}

function OfferCard({ offer }: { offer: EnergyOffer }) {
  const isSell = offer.side === "sell";
  return <article className="offer-card"><div className="offer-card-main"><div className={`avatar ${isSell ? "seller" : "buyer"}`}>{initials(offer.participant_name)}</div><div className="offer-person"><strong>{offer.participant_name}</strong><span>{isSell ? "Sell listing" : "Buy request"} · {offer.region_code}</span></div><span className="offer-source">{isSell ? offer.energy_source?.replace("_", " ") : "Buyer request"}</span></div>
    <div className="offer-card-values"><div><small>{isSell ? "Available energy" : "Requested energy"}</small><strong>{formatKwh(offer.available_wh || offer.energy_wh)}</strong></div><div><small>{isSell ? "Ask price" : "Max price"}</small><strong>{formatEuroCentsPerKwh(offer.price_cents_per_kwh)}</strong></div><div><small>Carbon factor</small><strong>{offer.carbon_factor ? formatFactor(offer.carbon_factor.value, offer.carbon_factor.unit) : "Buyer sets baseline"}</strong></div></div>
    <div className="offer-card-foot"><div>{offer.carbon_factor && <FactorBadge factor={offer.carbon_factor} />}<span className="quiet-meta"><Clock3 size={12} /> Expires {new Date(offer.expires_at).toLocaleDateString()}</span></div><span className="offer-status"><i />{offer.status.replace("_", " ")}</span></div>
  </article>;
}

function MatchCenterView(props: {
  scenario: Scenario; mode: Mode; setMode: (mode: Mode) => void; previews: Partial<Record<Mode, MatchPreview>>; activePreview?: MatchPreview;
  matching: boolean; onRun: () => void; onAccept: (proposal: Proposal, preview: MatchPreview) => void; acceptingId: string;
  activeTrade: TradeRecord | null; onSubmitTrade: (trade: TradeRecord) => void; submittingId: string;
}) {
  const [proposalToReview, setProposalToReview] = useState<{ proposal: Proposal; preview: MatchPreview } | null>(null);
  const preview = props.activePreview;
  return <div className="page-wrap">
    <PageTitle eyebrow="Deterministic ranking · v1" title="Match center" subtitle="Compare each candidate on price, carbon intensity and quantity fit, then review before reserving energy." />
    <div className="match-controls panel"><div className="mode-select"><button className={props.mode === "carbon_aware" ? "selected" : ""} onClick={() => props.setMode("carbon_aware")}><Leaf size={16} />Carbon-aware</button><button className={props.mode === "price_only" ? "selected" : ""} onClick={() => props.setMode("price_only")}><CircleDollarSign size={16} />Price-only</button></div><div className="match-control-right"><span className="algorithm-tag">{SCENARIOS.find((item) => item.id === props.scenario)?.label} · carbon-aware v1</span><button className="button primary" onClick={props.onRun} disabled={props.matching}>{props.matching ? <Loader2 className="spin" size={16} /> : <Sparkles size={16} />}{props.matching ? "Ranking candidates…" : "Run comparison"}</button></div></div>
    <div className="match-explainer"><ShieldCheck size={16} /><span>Same inputs and configuration produce the same order. Seller ask determines the price; buyer maximum is an eligibility filter.</span></div>
    {props.previews.carbon_aware && props.previews.price_only && <div className="match-mode-summary"><CompareModeCard mode="carbon_aware" preview={props.previews.carbon_aware} carbon={props.previews.carbon_aware.proposals.reduce((sum, p) => sum + (p.carbon_diff_dg || 0), 0)} energy={props.previews.carbon_aware.proposals.reduce((sum, p) => sum + p.matched_energy_wh, 0)} /><CompareModeCard mode="price_only" preview={props.previews.price_only} carbon={props.previews.price_only.proposals.reduce((sum, p) => sum + (p.carbon_diff_dg || 0), 0)} energy={props.previews.price_only.proposals.reduce((sum, p) => sum + p.matched_energy_wh, 0)} /></div>}
    {props.activeTrade && <AcceptedTrade trade={props.activeTrade} onSubmit={() => props.onSubmitTrade(props.activeTrade!)} submitting={props.submittingId === props.activeTrade.id} />}
    {preview ? <>
      <div className="section-heading-row results-heading"><div><p className="section-label">{props.mode === "carbon_aware" ? "Carbon-aware ranking" : "Price-only ranking"}</p><h2>{preview.proposals.length ? `${preview.proposals.length} proposed fills` : "No eligible matches"}</h2></div><div className="preview-expiry"><Clock3 size={14} /> Preview valid until {new Date(preview.expires_at * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</div></div>
      {preview.proposals.length ? <div className="proposal-list">{preview.proposals.map((proposal, index) => <ProposalCard key={`${preview.snapshot_version}-${proposal.id}`} proposal={proposal} rank={index + 1} preview={preview} onAccept={(next, source) => setProposalToReview({ proposal: next, preview: source })} accepting={props.acceptingId === proposal.id} />)}</div> : <EmptyState title="No compatible fills" detail="There are no eligible listings for the selected scenario and request limits." />}
    </> : <div className="empty-match panel"><div className="empty-illustration"><div><Sparkles size={25} /></div><span /><span /></div><p className="section-label">Start with a preview</p><h2>Find your best energy match</h2><p>Preview is read-only. It won’t reserve a listing or submit a transaction.</p><button className="button primary" onClick={props.onRun} disabled={props.matching}>{props.matching ? <Loader2 className="spin" size={16} /> : <Sparkles size={16} />}{props.matching ? "Ranking candidates…" : "Compare both modes"}</button></div>}
    {proposalToReview && <ProposalReviewDialog proposal={proposalToReview.proposal} onCancel={() => setProposalToReview(null)} onConfirm={() => { props.onAccept(proposalToReview.proposal, proposalToReview.preview); setProposalToReview(null); }} />}
  </div>;
}

function ProposalCard({ proposal, rank, preview, onAccept, accepting }: { proposal: Proposal; rank: number; preview: MatchPreview; onAccept: (proposal: Proposal, preview: MatchPreview) => void; accepting: boolean }) {
  return <article className={`proposal-card ${rank === 1 ? "winner" : ""}`}><div className="proposal-rank"><span>0{rank}</span><small>Rank</small></div><div className="proposal-content"><div className="proposal-top"><div className="participant-pair"><div className="participant-mini"><span className="avatar seller">{initials(proposal.seller_name)}</span><span><small>Seller</small><strong>{proposal.seller_name}</strong></span></div><ArrowLeftRight size={16} className="pair-arrow" /><div className="participant-mini"><span className="avatar buyer">{initials(proposal.buyer_name)}</span><span><small>Buyer · {proposal.buyer_region}</small><strong>{proposal.buyer_name}</strong></span></div></div><span className="status proposed"><Sparkles size={13} />PROPOSED</span></div>
      <div className="proposal-data-grid"><div><small>Proposed quantity</small><strong>{formatKwh(proposal.matched_energy_wh)}</strong></div><div><small>Seller ask</small><strong>{formatEuroCentsPerKwh(proposal.price_cents_per_kwh)}</strong><span>{formatEuroCents(proposal.total_cost_cents)} total</span></div><div><small>Scenario intensity</small><strong>{formatFactor(proposal.scenario_factor.value, proposal.scenario_factor.unit)}</strong><span>{proposal.scenario_factor.region} · {proposal.scenario_factor.source.name}</span></div><div><small>Est. emissions difference</small><strong>{proposal.carbon_diff_dg == null ? "Unavailable" : formatKgFromDg(proposal.carbon_diff_dg, proposal.scenario_factor.comparison_basis.gas)}</strong><span>{comparisonLabel(proposal.carbon_comparison_status)}</span></div></div>
      <div className="score-row"><div className="score-explanation"><b>Why this match</b><span>{proposal.mode === "price_only" ? "Price and quantity fit drive this ranking; carbon is display-only." : proposal.carbon_unrated ? "Carbon basis is not comparable, so the score uses price and quantity fit." : proposal.scenario_factor.value === 0 ? "Direct-combustion carbon ties across renewable sources; price and quantity fit break the tie." : "Ranked using fixed price, carbon and quantity-fit weights."}</span></div><div className="score-components"><ScorePill label="Price" value={proposal.score_breakdown.price} /><ScorePill label="Carbon" value={proposal.score_breakdown.carbon} /><ScorePill label="Quantity" value={proposal.score_breakdown.quantity_fit} /></div><div className="score-total"><small>Total score</small><strong>{formatScore(proposal.score_total)}</strong></div><button className="button primary accept-button" onClick={() => onAccept(proposal, preview)} disabled={accepting}>{accepting ? <Loader2 className="spin" size={15} /> : <Check size={15} />}{accepting ? "Reserving…" : "Review & accept"}</button></div>
      <div className="proposal-footer"><span className="factor-source"><FactorBadge factor={proposal.scenario_factor} /><span>Baseline: {proposal.baseline_factor?.id || "not available for this region"}</span></span><span className="proposal-id">{proposal.id}</span></div>
    </div></article>;
}

function ScorePill({ label, value }: { label: string; value: number | null }) {
  return <span className="score-pill"><small>{label}</small><b>{value == null ? "N/A" : value.toFixed(2)}</b></span>;
}

function AcceptedTrade({ trade, onSubmit, submitting }: { trade: TradeRecord; onSubmit: () => void; submitting: boolean }) {
  const [reviewing, setReviewing] = useState(false);
  return <><section className="accepted-panel panel"><div className="accepted-icon"><Check size={18} /></div><div className="accepted-copy"><p className="section-label">Reservation created · {trade.id}</p><h3>Ready for wallet submission</h3><p>Quantity is reserved. The trade is not complete until the backend verifies the on-chain receipt.</p></div><div className="accepted-state"><StatusBadge status={trade.status} /><strong>{formatKwh(trade.energy_wh)}</strong><span>{formatEuroCents(trade.total_cost_cents)}</span></div><button className="button primary" onClick={() => setReviewing(true)} disabled={submitting || trade.status !== "Offer"}>{submitting ? <Loader2 className="spin" size={16} /> : <Wallet size={16} />}{submitting ? "Submitting…" : "Submit to wallet"}</button></section>{reviewing && <TradeReviewDialog trade={trade} onCancel={() => setReviewing(false)} onConfirm={() => { setReviewing(false); onSubmit(); }} />}</>;
}

function ProposalReviewDialog({ proposal, onCancel, onConfirm }: { proposal: Proposal; onCancel: () => void; onConfirm: () => void }) {
  return <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onCancel(); }}><section className="review-dialog" role="dialog" aria-modal="true" aria-labelledby="proposal-dialog-title"><button className="dialog-close" onClick={onCancel} aria-label="Close review"><X size={17} /></button><p className="section-label">Confirm reservation</p><h2 id="proposal-dialog-title">Review this proposed trade</h2><p className="dialog-subtitle">Accepting reserves the energy and creates a trade row. Wallet submission happens as a separate step.</p>
    <div className="dialog-people"><span><small>Buyer</small><b>{proposal.buyer_name} · {proposal.buyer_region}</b></span><ArrowLeftRight size={15} /><span><small>Seller</small><b>{proposal.seller_name}</b></span></div>
    <div className="dialog-summary"><div><small>Exact quantity</small><b>{formatKwh(proposal.matched_energy_wh)}</b></div><div><small>Seller ask price</small><b>{formatEuroCentsPerKwh(proposal.price_cents_per_kwh)}</b></div><div><small>Total cost</small><b>{formatEuroCents(proposal.total_cost_cents)}</b></div><div><small>Scenario intensity</small><b>{formatFactor(proposal.scenario_factor.value, proposal.scenario_factor.unit)}</b></div><div className="dialog-wide"><small>Baseline and estimated difference</small><b>{proposal.baseline_factor ? `${proposal.baseline_factor.id} · ${proposal.carbon_diff_dg == null ? comparisonLabel(proposal.carbon_comparison_status) : formatKgFromDg(proposal.carbon_diff_dg, proposal.scenario_factor.comparison_basis.gas)}` : comparisonLabel(proposal.carbon_comparison_status)}</b></div></div>
    <div className="dialog-actions"><button className="button secondary" onClick={onCancel}>Back to preview</button><button className="button primary" onClick={onConfirm}><Check size={15} />Accept & reserve</button></div>
  </section></div>;
}

function TradeReviewDialog({ trade, onCancel, onConfirm }: { trade: TradeRecord; onCancel: () => void; onConfirm: () => void }) {
  const chainId = Number(import.meta.env.VITE_CHAIN_ID || 31337);
  return <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onCancel(); }}><section className="review-dialog" role="dialog" aria-modal="true" aria-labelledby="trade-dialog-title"><button className="dialog-close" onClick={onCancel} aria-label="Close review"><X size={17} /></button><p className="section-label">Wallet submission</p><h2 id="trade-dialog-title">Confirm on {chainName(chainId)}</h2><p className="dialog-subtitle">Your wallet will submit an audit record. It does not transfer funds or prove physical energy delivery.</p>
    <div className="dialog-people"><span><small>Buyer</small><b>{trade.buyer_id}</b></span><ArrowLeftRight size={15} /><span><small>Seller</small><b>{trade.seller_id}</b></span></div>
    <div className="dialog-summary"><div><small>Exact quantity</small><b>{formatKwh(trade.energy_wh)}</b></div><div><small>Seller ask price</small><b>{formatEuroCentsPerKwh(trade.price_cents_per_kwh)}</b></div><div><small>Total cost</small><b>{formatEuroCents(trade.total_cost_cents)}</b></div><div><small>Scenario intensity</small><b>{formatFactor(trade.scenario_factor.value, trade.scenario_factor.unit)}</b></div><div className="dialog-wide"><small>Est. emissions difference · {trade.baseline_factor?.id || "baseline unavailable"}</small><b>{trade.carbon_diff_dg == null ? comparisonLabel(trade.carbon_comparison_status) : formatKgFromDg(trade.carbon_diff_dg, trade.comparison_basis.gas)}</b></div><div className="dialog-wide"><small>Network</small><b>{chainName(chainId)} · chain {chainId} · authorization valid until {new Date(trade.valid_until * 1000).toLocaleTimeString()}</b></div></div>
    <div className="dialog-actions"><button className="button secondary" onClick={onCancel}>Back</button><button className="button primary" onClick={onConfirm}><Wallet size={15} />Open wallet</button></div>
  </section></div>;
}

function ActivityView({ trades, activeTrade, onSubmitTrade, submittingId, onReload }: { trades: TradeRecord[]; activeTrade: TradeRecord | null; onSubmitTrade: (trade: TradeRecord) => void; submittingId: string; onReload: () => void }) {
  return <div className="page-wrap"><PageTitle eyebrow="Audit trail" title="Trade activity" subtitle="Follow each accepted trade from wallet submission through backend verification." />
    {activeTrade && <AcceptedTrade trade={activeTrade} onSubmit={() => onSubmitTrade(activeTrade)} submitting={submittingId === activeTrade.id} />}
    <div className="panel activity-panel"><div className="panel-heading"><div><p className="section-label">Lifecycle</p><h3>Trade history</h3></div><button className="icon-button" onClick={onReload} aria-label="Refresh trades"><RefreshCcw size={16} /></button></div>
      {!trades.length ? <EmptyState title="No accepted trades yet" detail="Accepted proposals will appear here with a status and audit fields." /> : <div className="activity-list">{trades.map((trade) => <TradeDetailCard key={trade.id} trade={trade} />)}</div>}
    </div>
  </div>;
}

function TradeDetailCard({ trade }: { trade: TradeRecord }) {
  return <article className="trade-detail"><div className="trade-detail-header"><div className="trade-title"><span className="trade-icon"><Zap size={15} /></span><div><strong>{trade.id}</strong><small>{trade.scenario_id} · {new Date(trade.created_at).toLocaleString()}</small></div></div><StatusBadge status={trade.status} /></div>
    <div className="trade-detail-stats"><span><small>Energy</small><b>{formatKwh(trade.energy_wh)}</b></span><span><small>Ask price</small><b>{formatEuroCentsPerKwh(trade.price_cents_per_kwh)}</b></span><span><small>Total cost</small><b>{formatEuroCents(trade.total_cost_cents)}</b></span><span><small>Scenario intensity</small><b>{formatFactor(trade.scenario_factor.value, trade.scenario_factor.unit)}</b></span></div><div className="trade-carbon-note"><FactorBadge factor={trade.scenario_factor} /><span>Source: {trade.scenario_factor.source.name}</span><span>{trade.carbon_diff_dg == null ? comparisonLabel(trade.carbon_comparison_status) : `Est. difference: ${formatKgFromDg(trade.carbon_diff_dg, trade.comparison_basis.gas)} vs. ${trade.baseline_factor?.id || "baseline"}`}</span></div>
    <div className="trade-audit"><span>Basis <b>{trade.comparison_basis.gas} / {trade.comparison_basis.boundary}</b></span><span>Reservation <b>{trade.reservation_state}</b></span>{trade.transaction_hash && <span>Transaction <code>{shortHash(trade.transaction_hash)}</code></span>}{trade.failure_reason && <span>Reason <b>{trade.failure_reason.replaceAll("_", " ")}</b></span>}</div>
    {trade.transaction_hash && <div className="hash-grid"><HashField label="Baseline factor" hash={trade.baseline_factor_hash} /><HashField label="Scenario factor" hash={trade.scenario_factor_hash} /><HashField label="Score config" hash={trade.score_config_hash} /></div>}
  </article>;
}

function HashField({ label, hash }: { label: string; hash: string }) { return <span><small>{label} hash</small><code title={hash}>{shortHash(hash)}</code></span>; }

function TradeRow({ trade }: { trade: TradeRecord }) {
  return <tr><td><b className="mono">{trade.id}</b><small>{trade.scenario_id}</small></td><td><span>{trade.buyer_id} <ArrowLeftRight size={12} /> {trade.seller_id}</span></td><td className="right">{formatKwh(trade.energy_wh)}</td><td><StatusBadge status={trade.status} /></td><td><code>{shortHash(trade.transaction_hash)}</code></td></tr>;
}

function LoadingState({ label }: { label: string }) { return <div className="loading-state"><Loader2 size={19} className="spin" /><span>{label}</span></div>; }
function EmptyState({ title, detail, compact = false }: { title: string; detail: string; compact?: boolean }) { return <div className={`empty-state ${compact ? "compact" : ""}`}><span className="empty-icon"><Activity size={17} /></span><div><strong>{title}</strong><p>{detail}</p></div></div>; }
