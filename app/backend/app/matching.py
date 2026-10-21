import base64
import hashlib
import hmac
import json
import math
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.carbon import canonical_hash, factor_hash, factor_public, score_config_hash, score_config_payload
from app.config import settings
from app.models import CarbonFactor, EnergyOffer, Participant

ALGORITHM_VERSION = "carbon-aware-v1"
SCENARIO_YEAR = 2025
SCENARIOS = {"sunny-day", "low-generation", "demand-spike"}


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def sign_accept_token(proposal: dict[str, Any], snapshot_version: str, expires_at: int) -> str:
    key = settings.preview_token_signing_key.encode("utf-8")
    if len(key) < 32:
        raise RuntimeError("PREVIEW_TOKEN_SIGNING_KEY is missing. Run `npm run setup:local`, then restart the API.")
    claims = {"proposal": proposal, "snapshot_version": snapshot_version, "exp": expires_at}
    body = json.dumps(claims, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    encoded = b64url(body)
    signature = hmac.new(key, encoded.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded}.{b64url(signature)}"


def verify_accept_token(token: str, allow_expired: bool = False) -> dict[str, Any]:
    try:
        encoded, signature = token.split(".", 1)
        key = settings.preview_token_signing_key.encode("utf-8")
        expected = b64url(hmac.new(key, encoded.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError("bad signature")
        claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        if not allow_expired and int(claims["exp"]) < int(datetime.now(timezone.utc).timestamp()):
            raise ValueError("expired")
        return claims
    except Exception as exc:
        raise ValueError("The preview token is invalid or expired.") from exc


def _snapshot_version(offers: list[EnergyOffer], participants: dict[str, Participant], factors: dict[str, CarbonFactor], mode: str) -> str:
    used_factor_ids = sorted({o.carbon_factor_id for o in offers if o.side == "sell" and o.carbon_factor_id})
    buyer_ids = sorted({o.participant_id for o in offers if o.side == "buy"})
    snapshot = {
        "algorithm_version": ALGORITHM_VERSION,
        "scenario_year": SCENARIO_YEAR,
        "mode": mode,
        "offers": [
            {
                "id": o.id, "scenario_id": o.scenario_id, "participant_id": o.participant_id, "side": o.side,
                "energy_wh": o.energy_wh, "reserved_wh": o.reserved_wh, "settled_wh": o.settled_wh,
                "price_cents_per_kwh": o.price_cents_per_kwh, "currency": o.currency,
                "energy_source": o.energy_source, "carbon_factor_id": o.carbon_factor_id,
                "status": o.status, "expires_at": utc(o.expires_at).isoformat(),
                "created_at": utc(o.created_at).isoformat(),
            }
            for o in sorted(offers, key=lambda item: item.id)
        ],
        "buyer_regions": {pid: participants[pid].region_code for pid in buyer_ids},
        "factor_hashes": {fid: factor_hash(factors[fid]) for fid in used_factor_ids if fid in factors},
        "baseline_factors": {
            region: factor_hash(factor)
            for region, factor in sorted({f.region: f for f in factors.values() if f.region == "TR"}.items())
        },
        "score_config_hash": score_config_hash(mode, {"carbon": 4000, "price": 3000, "quantity_fit": 3000} if mode == "carbon_aware" else {"carbon": 0, "price": 5000, "quantity_fit": 5000}),
    }
    return canonical_hash(snapshot)


def _rank_one(
    listing: EnergyOffer,
    request: EnergyOffer,
    listing_remaining: int,
    request_remaining: int,
    seller: Participant,
    buyer: Participant,
    scenario_factor: CarbonFactor,
    baseline: CarbonFactor | None,
    mode: str,
):
    quantity = min(listing_remaining, request_remaining)
    q = quantity * 10000 // request_remaining
    p = 10000 - min(10000, max(0, listing.price_cents_per_kwh * 100))
    rated = scenario_factor.factor_use == "rankable" and scenario_factor.gas == "CO2" and scenario_factor.boundary == "combustion"
    c = 10000 - min(10000, max(0, scenario_factor.value_dg_per_kwh))
    mismatch = not rated
    if mode == "price_only":
        applied = {"carbon": 0, "price": 5000, "quantity_fit": 5000}
        score_bp = (applied["price"] * p + applied["quantity_fit"] * q + 5000) // 10000
        carbon_unrated = None
    elif mismatch:
        applied = {"carbon": 0, "price": 5000, "quantity_fit": 5000}
        score_bp = (applied["price"] * p + applied["quantity_fit"] * q + 5000) // 10000
        carbon_unrated = True
    else:
        applied = {"carbon": 4000, "price": 3000, "quantity_fit": 3000}
        score_bp = (applied["carbon"] * c + applied["price"] * p + applied["quantity_fit"] * q + 5000) // 10000
        carbon_unrated = False
    return {
        "listing": listing,
        "request": request,
        "seller": seller,
        "buyer": buyer,
        "factor": scenario_factor,
        "baseline": baseline,
        "quantity": quantity,
        "q": q,
        "p": p,
        "c": c,
        "rated": rated,
        "carbon_unrated": carbon_unrated,
        "applied_weights": applied,
        "score_bp": score_bp,
        "sort": (0 if rated or mode == "price_only" else 1, -score_bp, listing.price_cents_per_kwh, utc(listing.created_at).isoformat(), listing.id),
    }


def preview_matches(session: Session, scenario_id: str, mode: str) -> dict[str, Any]:
    if not session.in_transaction():
        dialect = session.get_bind().dialect.name
        if dialect == "sqlite":
            # sqlite3's legacy mode does not open a read transaction on SELECT alone.
            session.connection().exec_driver_sql("BEGIN")
        elif dialect == "postgresql":
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
    if scenario_id not in SCENARIOS:
        raise ValueError("scenario_id must be sunny-day, low-generation, or demand-spike.")
    if mode not in {"carbon_aware", "price_only"}:
        raise ValueError("mode must be carbon_aware or price_only.")
    offers = list(session.scalars(select(EnergyOffer).where(EnergyOffer.scenario_id == scenario_id).order_by(EnergyOffer.created_at, EnergyOffer.id)))
    participant_ids = sorted({o.participant_id for o in offers})
    participants = {p.id: p for p in session.scalars(select(Participant).where(Participant.id.in_(participant_ids)))}
    factors = {f.id: f for f in session.scalars(select(CarbonFactor))}
    snapshot = _snapshot_version(offers, participants, factors, mode)
    buys = sorted((o for o in offers if o.side == "buy"), key=lambda item: (utc(item.created_at), item.id))
    sells = [o for o in offers if o.side == "sell"]
    remaining = {o.id: o.available_wh for o in sells}
    proposals: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    ttl = settings.preview_token_ttl_seconds
    expires = int(now.timestamp()) + ttl
    for request in buys:
        request_remaining = request.available_wh
        buyer = participants[request.participant_id]
        if request.status not in {"active", "partially_filled"} or utc(request.expires_at) <= now:
            continue
        fill_index = 0
        while request_remaining > 0:
            ranked = []
            for listing in sells:
                seller = participants[listing.participant_id]
                if (
                    listing.scenario_id != request.scenario_id
                    or listing.status not in {"active", "partially_filled"}
                    or utc(listing.expires_at) <= now
                    or seller.id == buyer.id
                    or remaining[listing.id] <= 0
                    or listing.currency != request.currency
                    or listing.price_cents_per_kwh > request.price_cents_per_kwh
                    or not listing.carbon_factor_id
                    or listing.carbon_factor_id not in factors
                ):
                    continue
                scenario_factor = factors[listing.carbon_factor_id]
                baseline = next((f for f in factors.values() if f.region == buyer.region_code and f.factor_use == "rankable"), None)
                ranked.append(_rank_one(
                    listing, request, remaining[listing.id], request_remaining, seller, buyer,
                    scenario_factor, baseline, mode,
                ))
            if not ranked:
                break
            ranked.sort(key=lambda item: item["sort"])
            best = ranked[0]
            listing = best["listing"]
            quantity = best["quantity"]
            scenario_factor = best["factor"]
            baseline = best["baseline"]
            comparison_status = "comparable"
            carbon_diff = None
            if scenario_factor.gas != "CO2" or scenario_factor.boundary != "combustion" or scenario_factor.factor_use != "rankable":
                comparison_status = "basis_mismatch"
            elif baseline is None:
                comparison_status = "baseline_unavailable"
            elif baseline.gas != scenario_factor.gas or baseline.boundary != scenario_factor.boundary or baseline.factor_use != "rankable":
                comparison_status = "basis_mismatch"
            else:
                carbon_diff = quantity * (baseline.value_dg_per_kwh - scenario_factor.value_dg_per_kwh) // 1000
                product = quantity * (baseline.value_dg_per_kwh - scenario_factor.value_dg_per_kwh)
                if product < 0:
                    carbon_diff = -((-product) // 1000)
            applied = best["applied_weights"]
            cfg_payload = score_config_payload(mode, applied)
            fill_index += 1
            proposal_id = f"M-{request.id}-{fill_index}"
            proposal = {
                "id": proposal_id,
                "scenario_id": scenario_id,
                "mode": mode,
                "request_id": request.id,
                "listing_id": listing.id,
                "buyer_id": best["buyer"].id,
                "seller_id": best["seller"].id,
                "buyer_name": best["buyer"].display_name,
                "seller_name": best["seller"].display_name,
                "buyer_region": best["buyer"].region_code,
                "buyer_address": best["buyer"].wallet_address,
                "seller_address": best["seller"].wallet_address,
                "matched_energy_wh": quantity,
                "price_cents_per_kwh": listing.price_cents_per_kwh,
                "total_cost_cents": quantity * listing.price_cents_per_kwh // 1000,
                "scenario_factor_id": scenario_factor.id,
                "scenario_factor": factor_public(scenario_factor),
                "baseline_factor_id": baseline.id if baseline else None,
                "baseline_factor": factor_public(baseline) if baseline else None,
                "carbon_comparison_status": comparison_status,
                "carbon_diff_dg": carbon_diff,
                "estimated_scenario_emissions_dg": quantity * scenario_factor.value_dg_per_kwh // 1000,
                "estimated_baseline_emissions_dg": quantity * baseline.value_dg_per_kwh // 1000 if baseline and comparison_status == "comparable" else None,
                "emissions_unit": "kgCO2" if scenario_factor.gas == "CO2" else "kgCO2e",
                "declared_year": SCENARIO_YEAR,
                "carbon_unrated": best["carbon_unrated"],
                "score_total": best["score_bp"] / 10000,
                "score_total_bp": best["score_bp"],
                "score_breakdown": {
                    "price": best["p"] / 10000,
                    "quantity_fit": best["q"] / 10000,
                    "carbon": best["c"] / 10000 if mode == "carbon_aware" and not best["carbon_unrated"] else None,
                    "price_bp": best["p"], "quantity_fit_bp": best["q"],
                    "carbon_bp": best["c"] if mode == "carbon_aware" and not best["carbon_unrated"] else None,
                },
                "weights_configured_bp": cfg_payload["weights_configured_bp"],
                "weights_applied_bp": applied,
                "score_config_version": "v1",
                "score_config_hash": canonical_hash(cfg_payload),
                "algorithm_version": ALGORITHM_VERSION,
                "status": "proposed",
                "created_at": now.isoformat(),
                "expires_at": expires,
            }
            proposal["accept_token"] = sign_accept_token(proposal, snapshot, expires)
            proposals.append(proposal)
            remaining[listing.id] -= quantity
            request_remaining -= quantity
    return {"proposals": proposals, "snapshot_version": snapshot, "scenario_id": scenario_id, "mode": mode, "algorithm_version": ALGORITHM_VERSION, "expires_at": expires}

