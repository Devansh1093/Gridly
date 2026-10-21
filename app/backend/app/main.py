import asyncio
import hashlib
import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from web3 import Web3

from app import chain
from app.carbon import canonical_hash, factor_hash, factor_public
from app.config import settings
from app.database import Base, SessionLocal, engine, get_db
from app.matching import SCENARIOS, preview_matches, verify_accept_token
from app.models import CarbonFactor, EnergyOffer, Participant, TradeRecord, utcnow
from app.schemas import AcceptRequest, MatchPreviewRequest, OfferCreate, ParticipantCreate, TradePreparationRequest, TransactionRegistrationRequest
from app.seed import seed

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("energy-api")


def api_error(status: int, code: str, message: str, details: dict[str, Any] | None = None):
    raise HTTPException(status_code=status, detail={"code": code, "message": message, "details": details or {}})


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def current_offer_status(offer: EnergyOffer, now: datetime | None = None) -> str:
    if offer.status in {"cancelled", "expired"}:
        return offer.status
    if utc(offer.expires_at) <= (now or datetime.now(timezone.utc)):
        return "expired"
    available = offer.available_wh
    if available <= 0:
        return "filled"
    if offer.reserved_wh + offer.settled_wh > 0:
        return "partially_filled"
    return "active"


def sync_offer_status(offer: EnergyOffer) -> None:
    if offer.status not in {"cancelled", "expired"}:
        offer.status = current_offer_status(offer)


def offer_public(offer: EnergyOffer) -> dict[str, Any]:
    participant = offer.participant
    return {
        "id": offer.id,
        "scenario_id": offer.scenario_id,
        "participant_id": offer.participant_id,
        "participant_name": participant.display_name,
        "participant_type": participant.participant_type,
        "region_code": participant.region_code,
        "wallet_address": participant.wallet_address,
        "side": offer.side,
        "energy_wh": offer.energy_wh,
        "reserved_wh": offer.reserved_wh,
        "settled_wh": offer.settled_wh,
        "available_wh": offer.available_wh,
        "price_cents_per_kwh": offer.price_cents_per_kwh,
        "currency": offer.currency,
        "energy_source": offer.energy_source,
        "carbon_factor_id": offer.carbon_factor_id,
        "carbon_factor": factor_public(offer.carbon_factor),
        "status": current_offer_status(offer),
        "expires_at": utc(offer.expires_at).isoformat(),
        "created_at": utc(offer.created_at).isoformat(),
    }


def participant_public(participant: Participant) -> dict[str, Any]:
    return {
        "id": participant.id,
        "display_name": participant.display_name,
        "wallet_address": participant.wallet_address,
        "participant_type": participant.participant_type,
        "region_code": participant.region_code,
        "default_energy_source": participant.default_energy_source,
        "default_carbon_factor_id": participant.default_carbon_factor_id,
        "scenario_id": participant.scenario_id,
        "created_at": utc(participant.created_at).isoformat(),
    }


def trade_public(trade: TradeRecord) -> dict[str, Any]:
    return {
        "id": trade.id,
        "proposal_id": trade.proposal_id,
        "scenario_id": trade.scenario_id,
        "listing_id": trade.listing_id,
        "request_id": trade.request_id,
        "buyer_id": trade.buyer_id,
        "seller_id": trade.seller_id,
        "buyer_address": trade.buyer_address,
        "seller_address": trade.seller_address,
        "energy_wh": trade.energy_wh,
        "price_cents_per_kwh": trade.price_cents_per_kwh,
        "total_cost_cents": trade.total_cost_cents,
        "scenario_factor_id": trade.scenario_factor_id,
        "scenario_factor": factor_public(trade.scenario_factor),
        "baseline_factor_id": trade.baseline_factor_id,
        "baseline_factor": factor_public(trade.baseline_factor),
        "carbon_intensity_dg_per_kwh": trade.scenario_intensity_dg_per_kwh,
        "carbon_diff_dg": trade.carbon_diff_dg,
        "carbon_comparison_status": trade.carbon_comparison_status,
        "comparison_basis": {"gas": trade.comparison_gas, "boundary": trade.comparison_boundary},
        "declared_year": trade.declared_year,
        "baseline_factor_hash": trade.baseline_factor_hash,
        "scenario_factor_hash": trade.scenario_factor_hash,
        "score_config_hash": trade.score_config_hash,
        "score_config_version": trade.score_config_version,
        "mode": trade.mode,
        "score_total": trade.score_total_bp / 10000,
        "valid_until": trade.valid_until,
        "authorization_signature": trade.authorization_signature,
        "reservation_state": trade.reservation_state,
        "status": trade.status,
        "failure_reason": trade.failure_reason,
        "transaction_hash": trade.transaction_hash,
        "transaction_from": trade.transaction_from,
        "transaction_nonce": trade.transaction_nonce,
        "chain_id": trade.chain_id,
        "block_number": trade.block_number,
        "block_timestamp": trade.block_timestamp,
        "created_at": utc(trade.created_at).isoformat(),
        "confirmed_at": utc(trade.confirmed_at).isoformat() if trade.confirmed_at else None,
    }


def error_response(status: int, code: str, message: str, details: dict[str, Any] | None = None):
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "details": details or {}}})


def refresh_summary_offers(session: Session, offers: list[EnergyOffer]) -> None:
    changed = False
    now = datetime.now(timezone.utc)
    for offer in offers:
        if offer.status not in {"cancelled", "expired"} and utc(offer.expires_at) <= now:
            offer.status = "expired"
            changed = True
    if changed:
        session.commit()


def begin_write_lock(session: Session) -> None:
    if engine.dialect.name == "sqlite":
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")


def find_factor(session: Session, factor_id: str | None) -> CarbonFactor | None:
    return session.get(CarbonFactor, factor_id) if factor_id else None


def matches_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    keys = (
        "id", "scenario_id", "request_id", "listing_id", "buyer_id", "seller_id", "matched_energy_wh",
        "price_cents_per_kwh", "total_cost_cents", "scenario_factor_id", "baseline_factor_id",
        "carbon_comparison_status", "carbon_diff_dg", "score_total_bp", "score_config_hash",
    )
    return all(left.get(key) == right.get(key) for key in keys)


def release_trade(session: Session, trade: TradeRecord, failure_reason: str) -> None:
    if trade.reservation_state != "reserved":
        return
    listing = session.get(EnergyOffer, trade.listing_id)
    request = session.get(EnergyOffer, trade.request_id)
    if listing:
        listing.reserved_wh = max(0, listing.reserved_wh - trade.energy_wh)
        sync_offer_status(listing)
    if request:
        request.reserved_wh = max(0, request.reserved_wh - trade.energy_wh)
        sync_offer_status(request)
    trade.reservation_state = "released"
    trade.status = "Fail"
    trade.failure_reason = failure_reason


def settle_trade(session: Session, trade: TradeRecord, block_number: int, block_timestamp: int) -> None:
    if trade.reservation_state == "settled":
        return
    if trade.reservation_state != "reserved":
        return
    listing = session.get(EnergyOffer, trade.listing_id)
    request = session.get(EnergyOffer, trade.request_id)
    if listing:
        listing.reserved_wh = max(0, listing.reserved_wh - trade.energy_wh)
        listing.settled_wh += trade.energy_wh
        sync_offer_status(listing)
    if request:
        request.reserved_wh = max(0, request.reserved_wh - trade.energy_wh)
        request.settled_wh += trade.energy_wh
        sync_offer_status(request)
    trade.reservation_state = "settled"
    trade.status = "Done"
    trade.block_number = block_number
    trade.block_timestamp = block_timestamp
    trade.confirmed_at = datetime.now(timezone.utc)
    trade.failure_reason = None


async def reconcile_once() -> None:
    try:
        if not settings.contract_address:
            return
        client = chain.web3_client()
        latest = client.eth.get_block("latest")
    except Exception as exc:
        logger.debug("Chain reconciliation deferred: %s", exc)
        return
    with SessionLocal() as session:
        rows = list(session.scalars(select(TradeRecord).where(TradeRecord.reservation_state == "reserved").order_by(TradeRecord.created_at)))
        for trade in rows:
            try:
                exists = chain.trade_event_exists(trade)
                if exists:
                    event_client, _contract, log = chain.matching_event_for_trade(trade)
                    if log and chain.verify_event_payload(log, trade):
                        receipt = event_client.eth.get_transaction_receipt(log["transactionHash"])
                        block = event_client.eth.get_block(receipt["blockNumber"])
                        if receipt["status"] == 1 and latest["number"] - receipt["blockNumber"] + 1 >= settings.confirmation_blocks:
                            trade.transaction_hash = Web3.to_hex(log["transactionHash"])
                            settle_trade(session, trade, receipt["blockNumber"], block["timestamp"])
                            continue
                if trade.transaction_hash:
                    tx_client, receipt = chain.receipt_for_hash(trade.transaction_hash)
                    if receipt is not None and latest["number"] - receipt["blockNumber"] + 1 >= settings.confirmation_blocks:
                        if receipt["status"] == 0:
                            release_trade(session, trade, "CHAIN_REVERTED")
                        else:
                            _client, _contract, log = chain.matching_event_for_trade(trade)
                            if log and chain.verify_event_payload(log, trade):
                                block = tx_client.eth.get_block(receipt["blockNumber"])
                                settle_trade(session, trade, receipt["blockNumber"], block["timestamp"])
                    elif (
                        receipt is None
                        and trade.transaction_from
                        and int((datetime.now(timezone.utc) - utc(trade.created_at)).total_seconds()) >= 3600
                        and not exists
                        and chain.finalized_nonce_replacement(trade, settings.confirmation_blocks)
                    ):
                        release_trade(session, trade, "TRANSACTION_REPLACED")
                elif trade.status == "Offer" and int(datetime.now(timezone.utc).timestamp()) > trade.valid_until:
                    trade.status = "Fail"
                    trade.failure_reason = "OFFER_TTL_EXPIRED"
                if trade.reservation_state == "reserved" and trade.status == "Fail" and int(latest["timestamp"]) > trade.valid_until and latest["number"] >= settings.confirmation_blocks:
                    # The contract rejects this signed permit after validUntil; require an absent registry entry on a finalized head.
                    if not chain.trade_event_exists(trade):
                        release_trade(session, trade, trade.failure_reason or "OFFER_TTL_EXPIRED")
            except Exception as exc:
                logger.info("Could not reconcile trade %s yet: %s", trade.id, exc)
        session.commit()


async def reconciliation_loop() -> None:
    while True:
        await reconcile_once()
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        if not session.scalar(select(Participant.id).limit(1)):
            seed(session, "all", reset=False)
    task = asyncio.create_task(reconciliation_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Gridly P2P Energy Trading API", version="1.0.0", lifespan=lifespan)
frontend_origins = [origin.strip() for origin in settings.frontend_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=frontend_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Idempotency-Key"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict) and {"code", "message"}.issubset(detail):
        return JSONResponse(status_code=exc.status_code, content={"error": detail})
    return error_response(exc.status_code, "REQUEST_FAILED", str(detail))


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_request: Request, exc: RequestValidationError):
    return error_response(422, "VALIDATION_ERROR", "Check the submitted fields and try again.", {"fields": exc.errors(include_context=False)})


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request: Request, exc: Exception):
    logger.exception("Unhandled API error", exc_info=exc)
    return error_response(500, "INTERNAL_ERROR", "The server could not complete this request.")


@app.get("/api/v1/health")
def health():
    connected = False
    if settings.contract_address:
        try:
            client = chain.web3_client()
            connected = bool(client.eth.get_code(chain.require_contract()))
        except Exception:
            connected = False
    return {"status": "ok", "chain_configured": bool(settings.contract_address), "chain_connected": connected, "chain_id": settings.chain_id}


@app.get("/api/v1/factors")
def list_factors(session: Session = Depends(get_db)):
    return [factor_public(factor) for factor in session.scalars(select(CarbonFactor).order_by(CarbonFactor.id))]


@app.get("/api/v1/participants")
def list_participants(session: Session = Depends(get_db)):
    return [participant_public(p) for p in session.scalars(select(Participant).order_by(Participant.id))]


@app.post("/api/v1/participants", status_code=201)
def create_participant(body: ParticipantCreate, session: Session = Depends(get_db)):
    wallet = body.wallet_address
    if wallet and not Web3.is_address(wallet):
        api_error(422, "VALIDATION_ERROR", "Enter a valid EVM wallet address.")
    source_to_factor = {"solar": "solar_direct_co2", "wind": "wind_direct_co2", "grid_mix": "grid_tr_iea2025"}
    if body.default_energy_source and body.default_energy_source not in source_to_factor:
        api_error(422, "VALIDATION_ERROR", "Supported sources are solar, wind, and grid_mix.")
    participant = Participant(
        id=f"P-{uuid.uuid4().hex[:12]}", display_name=body.display_name,
        participant_type=body.participant_type, region_code=body.region_code.upper(),
        wallet_address=Web3.to_checksum_address(wallet) if wallet else None,
        default_energy_source=body.default_energy_source,
        default_carbon_factor_id=source_to_factor.get(body.default_energy_source or ""),
        scenario_id=None, created_at=datetime.now(timezone.utc),
    )
    session.add(participant)
    session.commit()
    return participant_public(participant)


@app.get("/api/v1/participants/{participant_id}")
def get_participant(participant_id: str, session: Session = Depends(get_db)):
    participant = session.get(Participant, participant_id)
    if not participant:
        api_error(404, "PARTICIPANT_NOT_FOUND", "Participant was not found.")
    return participant_public(participant)


@app.get("/api/v1/offers")
def list_offers(
    side: str | None = Query(default=None, pattern="^(buy|sell)$"),
    status: str | None = Query(default=None),
    scenario_id: str | None = Query(default=None),
    session: Session = Depends(get_db),
):
    query = select(EnergyOffer).order_by(EnergyOffer.created_at, EnergyOffer.id)
    if side:
        query = query.where(EnergyOffer.side == side)
    if scenario_id and scenario_id != "all":
        query = query.where(EnergyOffer.scenario_id == scenario_id)
    offers = list(session.scalars(query))
    refresh_summary_offers(session, offers)
    result = [offer_public(o) for o in offers]
    return [o for o in result if not status or o["status"] == status]


@app.get("/api/v1/offers/{offer_id}")
def get_offer(offer_id: str, session: Session = Depends(get_db)):
    offer = session.get(EnergyOffer, offer_id)
    if not offer:
        api_error(404, "OFFER_NOT_FOUND", "The sell listing or buy request was not found.")
    return offer_public(offer)


@app.post("/api/v1/offers", status_code=201)
def create_offer(body: OfferCreate, session: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    expires = utc(body.expires_at)
    if expires <= now:
        api_error(422, "OFFER_EXPIRED", "Expiry must be in the future.")
    if body.scenario_id not in SCENARIOS:
        api_error(422, "VALIDATION_ERROR", "Choose a supported demo scenario.")
    participant = session.get(Participant, body.participant_id)
    if not participant:
        api_error(404, "PARTICIPANT_NOT_FOUND", "Select an existing participant.")
    if body.side == "sell" and participant.participant_type not in {"prosumer", "both"}:
        api_error(422, "VALIDATION_ERROR", "Only a prosumer can publish a sell listing.")
    if body.side == "buy" and participant.participant_type not in {"consumer", "both"}:
        api_error(422, "VALIDATION_ERROR", "Only a consumer can publish a buy request.")
    factor = None
    energy_source = None
    if body.side == "sell":
        source_to_factor = {"solar": "solar_direct_co2", "wind": "wind_direct_co2", "grid_mix": "grid_tr_iea2025"}
        energy_source = body.energy_source or participant.default_energy_source or "mixed"
        expected_factor_id = source_to_factor.get(energy_source)
        if not expected_factor_id:
            api_error(422, "VALIDATION_ERROR", "Supported sell sources are solar, wind, and grid_mix.")
        factor_id = body.carbon_factor_id or participant.default_carbon_factor_id or expected_factor_id
        if factor_id != expected_factor_id:
            api_error(422, "VALIDATION_ERROR", "The selected carbon factor must match the declared energy source.")
        factor = find_factor(session, factor_id)
        if not factor or factor.factor_use != "rankable":
            api_error(422, "VALIDATION_ERROR", "Choose a rankable carbon factor for the sell listing.")
    offer = EnergyOffer(
        id=f"O-{uuid.uuid4().hex}", scenario_id=body.scenario_id,
        participant_id=participant.id, side=body.side, energy_wh=body.energy_wh,
        reserved_wh=0, settled_wh=0, price_cents_per_kwh=body.price_cents_per_kwh,
        currency=body.currency, energy_source=energy_source,
        carbon_factor_id=factor.id if factor else None, status="active",
        expires_at=expires, created_at=now,
    )
    session.add(offer)
    session.commit()
    session.refresh(offer)
    return offer_public(offer)


@app.post("/api/v1/offers/{offer_id}/cancel")
def cancel_offer(offer_id: str, session: Session = Depends(get_db)):
    offer = session.get(EnergyOffer, offer_id)
    if not offer:
        api_error(404, "OFFER_NOT_FOUND", "The sell listing or buy request was not found.")
    held = session.scalar(select(func.count()).select_from(TradeRecord).where(
        (TradeRecord.listing_id == offer_id) | (TradeRecord.request_id == offer_id),
        TradeRecord.reservation_state == "reserved",
    ))
    if held:
        api_error(409, "RESERVATION_ACTIVE", "This listing or request has a reserved trade and cannot be cancelled yet.")
    offer.status = "cancelled"
    session.commit()
    return offer_public(offer)


@app.post("/api/v1/matches/preview")
def match_preview(body: MatchPreviewRequest, session: Session = Depends(get_db)):
    try:
        return preview_matches(session, body.scenario_id, body.mode)
    except RuntimeError as exc:
        api_error(503, "PREVIEW_SIGNING_NOT_CONFIGURED", str(exc))
    except ValueError as exc:
        api_error(422, "VALIDATION_ERROR", str(exc))


@app.post("/api/v1/matches/{proposal_id}/accept")
def accept_match(
    proposal_id: str,
    body: AcceptRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=160),
    session: Session = Depends(get_db),
):
    fingerprint = hashlib.sha256(json.dumps({
        "proposal_id": proposal_id, "accept_token": body.accept_token, "snapshot_version": body.snapshot_version,
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    try:
        begin_write_lock(session)
        existing = session.scalar(select(TradeRecord).where(TradeRecord.idempotency_key == idempotency_key))
        if existing:
            if existing.idempotency_fingerprint != fingerprint:
                session.rollback()
                api_error(409, "IDEMPOTENCY_KEY_REUSED", "This Idempotency-Key was already used with a different acceptance request.")
            result = trade_public(existing)
            session.rollback()
            return {"trade": result, "idempotent_replay": True}
        try:
            claims = verify_accept_token(body.accept_token, allow_expired=True)
        except ValueError:
            session.rollback()
            api_error(409, "stale_preview", "The preview token is invalid; review a fresh preview.")
        proposal = claims.get("proposal", {})
        scenario_id = proposal.get("scenario_id")
        mode = proposal.get("mode")
        if claims.get("snapshot_version") != body.snapshot_version or proposal.get("id") != proposal_id:
            session.rollback()
            api_error(409, "stale_preview", "The preview token does not match this proposal.")
        fresh = preview_matches(session, scenario_id, mode)
        candidate = next((p for p in fresh["proposals"] if p["id"] == proposal_id), None)
        if int(claims.get("exp", 0)) <= int(datetime.now(timezone.utc).timestamp()) or fresh["snapshot_version"] != body.snapshot_version or not candidate or not matches_equal(proposal, candidate):
            session.rollback()
            fresh = preview_matches(session, scenario_id, mode)
            api_error(409, "stale_preview", "Offers or ranking inputs changed. Review the fresh preview before accepting.", {"fresh_preview": fresh})
        listing_id, request_id = candidate["listing_id"], candidate["request_id"]
        locked = list(session.scalars(
            select(EnergyOffer).where(EnergyOffer.id.in_([listing_id, request_id])).order_by(EnergyOffer.id).with_for_update()
        ))
        offers_by_id = {offer.id: offer for offer in locked}
        listing, request = offers_by_id.get(listing_id), offers_by_id.get(request_id)
        if not listing or not request or listing.scenario_id != request.scenario_id or listing.scenario_id != scenario_id:
            session.rollback()
            fresh = preview_matches(session, scenario_id, mode)
            api_error(409, "stale_preview", "The listing or request changed. Review the fresh preview.", {"fresh_preview": fresh})
        if listing.available_wh < candidate["matched_energy_wh"] or request.available_wh < candidate["matched_energy_wh"]:
            session.rollback()
            fresh = preview_matches(session, scenario_id, mode)
            api_error(409, "stale_preview", "There is not enough available quantity. Review the fresh preview.", {"fresh_preview": fresh})
        buyer = session.get(Participant, candidate["buyer_id"])
        seller = session.get(Participant, candidate["seller_id"])
        if not buyer or not seller or not buyer.wallet_address or not seller.wallet_address:
            session.rollback()
            api_error(422, "WALLET_REQUIRED", "Both participants need an EVM wallet address before a trade can be accepted.")
        if not Web3.is_address(buyer.wallet_address) or not Web3.is_address(seller.wallet_address) or buyer.wallet_address.lower() == seller.wallet_address.lower():
            session.rollback()
            api_error(422, "INVALID_TRADE_PARTICIPANTS", "Buyer and seller must have distinct valid EVM addresses.")
        sequence = (session.scalar(select(func.max(TradeRecord.sequence)).where(TradeRecord.request_id == request_id)) or 0) + 1
        trade_id = f"T-{request_id}-{sequence}"
        scenario_factor = session.get(CarbonFactor, candidate["scenario_factor_id"])
        baseline_factor = session.get(CarbonFactor, candidate["baseline_factor_id"]) if candidate.get("baseline_factor_id") else None
        if not scenario_factor:
            session.rollback()
            api_error(422, "FACTOR_MISSING", "The scenario factor is unavailable; this match cannot be accepted.")
        trade = TradeRecord(
            id=trade_id, sequence=sequence, proposal_id=proposal_id,
            idempotency_key=idempotency_key, idempotency_fingerprint=fingerprint,
            listing_id=listing_id, request_id=request_id, scenario_id=scenario_id,
            buyer_id=buyer.id, seller_id=seller.id,
            buyer_address=Web3.to_checksum_address(buyer.wallet_address),
            seller_address=Web3.to_checksum_address(seller.wallet_address),
            energy_wh=candidate["matched_energy_wh"], price_cents_per_kwh=candidate["price_cents_per_kwh"],
            total_cost_cents=candidate["total_cost_cents"], scenario_factor_id=scenario_factor.id,
            baseline_factor_id=baseline_factor.id if baseline_factor else None,
            scenario_intensity_dg_per_kwh=scenario_factor.value_dg_per_kwh,
            carbon_diff_dg=candidate["carbon_diff_dg"], carbon_comparison_status=candidate["carbon_comparison_status"],
            declared_year=candidate["declared_year"], comparison_gas=scenario_factor.gas,
            comparison_boundary=scenario_factor.boundary,
            baseline_factor_hash=factor_hash(baseline_factor) if baseline_factor else chain.ZERO_BYTES32,
            scenario_factor_hash=factor_hash(scenario_factor), score_config_hash=candidate["score_config_hash"],
            score_config_version=candidate["score_config_version"], mode=mode,
            score_total_bp=candidate["score_total_bp"],
            valid_until=int(datetime.now(timezone.utc).timestamp()) + 15 * 60,
            status="Offer", reservation_state="reserved", created_at=datetime.now(timezone.utc),
        )
        listing.reserved_wh += trade.energy_wh
        request.reserved_wh += trade.energy_wh
        sync_offer_status(listing)
        sync_offer_status(request)
        session.add(trade)
        session.commit()
        session.refresh(trade)
        return {"trade": trade_public(trade), "idempotent_replay": False}
    except HTTPException:
        session.rollback()
        raise
    except Exception as exc:
        session.rollback()
        logger.exception("Accept failed", exc_info=exc)
        api_error(409, "stale_preview", "The reservation could not be created safely; review a fresh preview.")


@app.post("/api/v1/trades")
def prepare_trade(body: TradePreparationRequest, session: Session = Depends(get_db)):
    trade = session.get(TradeRecord, body.trade_id)
    if not trade:
        api_error(404, "TRADE_NOT_FOUND", "Accepted trade was not found.")
    if trade.status != "Offer" or trade.reservation_state != "reserved":
        api_error(409, "TRADE_NOT_READY", "Only a trade ready for wallet submission can be prepared.")
    try:
        payload, signature = chain.sign_trade_payload(trade)
    except RuntimeError as exc:
        api_error(503, "CHAIN_NOT_CONFIGURED", str(exc))
    trade.authorization_signature = signature
    session.commit()
    return {
        "trade_id": trade.id,
        "chain_id": settings.chain_id,
        "contract_address": chain.require_contract(),
        "contract_payload": payload,
        "valid_until": trade.valid_until,
        "authorization_signature": signature,
    }


@app.post("/api/v1/trades/{trade_id}/transaction")
def register_transaction(trade_id: str, body: TransactionRegistrationRequest, session: Session = Depends(get_db)):
    trade = session.get(TradeRecord, trade_id)
    if not trade:
        api_error(404, "TRADE_NOT_FOUND", "Accepted trade was not found.")
    tx_hash = body.transaction_hash.lower()
    if trade.transaction_hash and trade.transaction_hash.lower() == tx_hash:
        return trade_public(trade)
    if trade.status != "Offer" or trade.reservation_state != "reserved" or not trade.authorization_signature:
        api_error(409, "TRADE_NOT_READY", "This trade is not ready to register a wallet transaction.")
    try:
        client, tx = chain.verify_submitted_transaction(tx_hash, trade)
    except RuntimeError as exc:
        api_error(503, "CHAIN_NOT_CONFIGURED", str(exc))
    except ValueError as exc:
        api_error(422, "CHAIN_SUBMISSION_FAILED", str(exc))
    trade.transaction_hash = tx_hash
    trade.transaction_from = Web3.to_checksum_address(tx["from"])
    trade.transaction_nonce = tx["nonce"]
    trade.chain_id = client.eth.chain_id
    trade.status = "Pending"
    session.commit()
    return trade_public(trade)


@app.get("/api/v1/trades")
def list_trades(scenario_id: str | None = None, session: Session = Depends(get_db)):
    query = select(TradeRecord).order_by(TradeRecord.created_at.desc(), TradeRecord.id)
    if scenario_id and scenario_id != "all":
        query = query.where(TradeRecord.scenario_id == scenario_id)
    return [trade_public(t) for t in session.scalars(query.limit(200))]


@app.get("/api/v1/trades/by-transaction/{transaction_hash}")
def get_trade_by_transaction(transaction_hash: str, session: Session = Depends(get_db)):
    trade = session.scalar(select(TradeRecord).where(func.lower(TradeRecord.transaction_hash) == transaction_hash.lower()))
    if not trade:
        api_error(404, "TRADE_NOT_FOUND", "No trade is registered for this transaction hash.")
    return trade_public(trade)


@app.get("/api/v1/trades/{trade_id}")
def get_trade(trade_id: str, session: Session = Depends(get_db)):
    trade = session.get(TradeRecord, trade_id)
    if not trade:
        api_error(404, "TRADE_NOT_FOUND", "Accepted trade was not found.")
    return trade_public(trade)


@app.post("/api/v1/trades/{trade_id}/cancel")
def cancel_trade(trade_id: str, session: Session = Depends(get_db)):
    trade = session.get(TradeRecord, trade_id)
    if not trade:
        api_error(404, "TRADE_NOT_FOUND", "Accepted trade was not found.")
    if trade.status != "Offer" or trade.transaction_hash:
        api_error(409, "TRADE_CANNOT_CANCEL", "Only a trade without a submitted transaction can be cancelled.")
    # The EIP-712 permit remains usable until valid_until, so quantity stays reserved
    # until the chain deadline is finalized and tradeExists confirms absence.
    trade.status = "Fail"
    trade.failure_reason = "USER_CANCELLED"
    session.commit()
    return trade_public(trade)


@app.get("/api/v1/dashboard/summary")
def dashboard_summary(scenario_id: str = "all", session: Session = Depends(get_db)):
    if scenario_id != "all" and scenario_id not in SCENARIOS:
        api_error(422, "VALIDATION_ERROR", "Choose all or one supported demo scenario.")
    offer_query = select(EnergyOffer)
    trade_query = select(TradeRecord)
    if scenario_id != "all":
        offer_query = offer_query.where(EnergyOffer.scenario_id == scenario_id)
        trade_query = trade_query.where(TradeRecord.scenario_id == scenario_id)
    offers = list(session.scalars(offer_query))
    refresh_summary_offers(session, offers)
    trades = list(session.scalars(trade_query.order_by(TradeRecord.created_at.desc())))
    factors = {f.id: f for f in session.scalars(select(CarbonFactor))}
    done = [t for t in trades if t.status == "Done"]
    pending_count = sum(t.status == "Pending" for t in trades)
    failed_count = sum(t.status == "Fail" for t in trades)
    reserved_wh = sum(t.energy_wh for t in trades if t.status in {"Offer", "Pending"} and t.reservation_state == "reserved")
    energy_wh = sum(t.energy_wh for t in done)
    renewable_wh = sum(t.energy_wh for t in done if (factors.get(t.scenario_factor_id) and factors[t.scenario_factor_id].id in {"solar_direct_co2", "wind_direct_co2"}))
    average_numerator = 0
    average_denominator = 0
    excluded_basis_count = 0
    comparable_diff_dg = 0
    excluded_emissions_count = 0
    average_factor_ids: set[str] = set()
    for trade in done:
        factor = factors.get(trade.scenario_factor_id)
        if not factor or (factor.gas, factor.boundary) != ("CO2", "combustion"):
            excluded_basis_count += 1
        else:
            average_numerator += trade.energy_wh * trade.scenario_intensity_dg_per_kwh
            average_denominator += trade.energy_wh
            average_factor_ids.add(factor.id)
        if trade.carbon_comparison_status == "comparable" and trade.baseline_factor_id and trade.scenario_factor_id and trade.carbon_diff_dg is not None:
            comparable_diff_dg += trade.carbon_diff_dg
        else:
            excluded_emissions_count += 1
    avg_dg = (2 * average_numerator + average_denominator) // (2 * average_denominator) if average_denominator else None
    active_buys = sum(o.side == "buy" and current_offer_status(o) in {"active", "partially_filled"} for o in offers)
    active_sells = sum(o.side == "sell" and current_offer_status(o) in {"active", "partially_filled"} for o in offers)
    return {
        "scenario_id": scenario_id,
        "total_proposed_energy_wh": reserved_wh,
        "energy_traded_wh": energy_wh,
        "done_trade_count": len(done),
        "renewable_energy_matched_wh": renewable_wh,
        "average_carbon_intensity_g_per_kwh": avg_dg / 10 if avg_dg is not None else None,
        "average_carbon_intensity_dg_per_kwh": avg_dg,
        "average_carbon_intensity_basis": {"gas": "CO2", "boundary": "combustion"},
        "excluded_basis_count": excluded_basis_count,
        "estimated_emissions_difference_dg": comparable_diff_dg,
        "estimated_emissions_difference_kg": comparable_diff_dg / 10000,
        "emissions_baseline_factor_id": "grid_tr_iea2025",
        "emissions_baseline_factor": factor_public(factors.get("grid_tr_iea2025")),
        "average_intensity_factors": [factor_public(factors[fid]) for fid in sorted(average_factor_ids)],
        "emissions_excluded_match_count": excluded_emissions_count,
        "pending_transaction_count": pending_count,
        "failed_transaction_count": failed_count,
        "active_buy_request_count": active_buys,
        "active_sell_listing_count": active_sells,
        "recent_trades": [trade_public(t) for t in trades[:5]],
    }


@app.get("/api/v1/dashboard/timeseries")
def dashboard_timeseries(period: str = Query(default="day", pattern="^(day|week)$"), scenario_id: str = "all", session: Session = Depends(get_db)):
    if scenario_id != "all" and scenario_id not in SCENARIOS:
        api_error(422, "VALIDATION_ERROR", "Choose all or one supported demo scenario.")
    query = select(TradeRecord).where(TradeRecord.status == "Done")
    if scenario_id != "all":
        query = query.where(TradeRecord.scenario_id == scenario_id)
    grouped: dict[str, dict[str, int]] = {}
    for trade in session.scalars(query.order_by(TradeRecord.confirmed_at)):
        stamp = trade.confirmed_at or trade.created_at
        key = utc(stamp).date().isoformat() if period == "day" else f"{utc(stamp).isocalendar().year}-W{utc(stamp).isocalendar().week:02d}"
        bucket = grouped.setdefault(key, {"energy_wh": 0, "trade_count": 0, "emissions_difference_dg": 0})
        bucket["energy_wh"] += trade.energy_wh
        bucket["trade_count"] += 1
        if trade.carbon_comparison_status == "comparable" and trade.carbon_diff_dg is not None:
            bucket["emissions_difference_dg"] += trade.carbon_diff_dg
    return [{"period": key, **value} for key, value in sorted(grouped.items())]
