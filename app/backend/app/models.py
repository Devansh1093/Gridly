from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Participant(Base):
    __tablename__ = "participants"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    wallet_address: Mapped[str | None] = mapped_column(String(42))
    participant_type: Mapped[str] = mapped_column(String(24), nullable=False)
    region_code: Mapped[str] = mapped_column(String(8), nullable=False)
    default_energy_source: Mapped[str | None] = mapped_column(String(32))
    default_carbon_factor_id: Mapped[str | None] = mapped_column(ForeignKey("carbon_factors.id"))
    scenario_id: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class CarbonFactor(Base):
    __tablename__ = "carbon_factors"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    value_dg_per_kwh: Mapped[int] = mapped_column(Integer, nullable=False)
    unit: Mapped[str] = mapped_column(String(24), nullable=False)
    region: Mapped[str] = mapped_column(String(8), nullable=False)
    data_year: Mapped[int | None] = mapped_column(Integer)
    edition_year: Mapped[int | None] = mapped_column(Integer)
    demo_scenario: Mapped[str] = mapped_column(String(80), nullable=False)
    gas: Mapped[str] = mapped_column(String(8), nullable=False)
    boundary: Mapped[str] = mapped_column(String(24), nullable=False)
    factor_use: Mapped[str] = mapped_column(String(24), nullable=False)
    provenance: Mapped[str] = mapped_column(String(24), nullable=False)
    source_name: Mapped[str] = mapped_column(String(240), nullable=False)
    source_table: Mapped[str | None] = mapped_column(String(120))
    source_row: Mapped[str | None] = mapped_column(String(120))
    fixture: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    simulated: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class EnergyOffer(Base):
    __tablename__ = "energy_offers"
    __table_args__ = (UniqueConstraint("scenario_id", "id", name="uq_offer_scenario_id"),)

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    scenario_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    participant_id: Mapped[str] = mapped_column(ForeignKey("participants.id"), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    energy_wh: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_wh: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    settled_wh: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    price_cents_per_kwh: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    energy_source: Mapped[str | None] = mapped_column(String(32))
    carbon_factor_id: Mapped[str | None] = mapped_column(ForeignKey("carbon_factors.id"))
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    participant: Mapped[Participant] = relationship(foreign_keys=[participant_id])
    carbon_factor: Mapped[CarbonFactor | None] = relationship(foreign_keys=[carbon_factor_id])

    @property
    def available_wh(self) -> int:
        return max(0, self.energy_wh - self.reserved_wh - self.settled_wh)


class TradeRecord(Base):
    __tablename__ = "trade_records"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_trade_idempotency_key"),
        UniqueConstraint("request_id", "sequence", name="uq_trade_request_sequence"),
    )

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    proposal_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    idempotency_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    listing_id: Mapped[str] = mapped_column(ForeignKey("energy_offers.id"), nullable=False)
    request_id: Mapped[str] = mapped_column(ForeignKey("energy_offers.id"), nullable=False)
    scenario_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    buyer_id: Mapped[str] = mapped_column(ForeignKey("participants.id"), nullable=False)
    seller_id: Mapped[str] = mapped_column(ForeignKey("participants.id"), nullable=False)
    buyer_address: Mapped[str] = mapped_column(String(42), nullable=False)
    seller_address: Mapped[str] = mapped_column(String(42), nullable=False)
    energy_wh: Mapped[int] = mapped_column(Integer, nullable=False)
    price_cents_per_kwh: Mapped[int] = mapped_column(Integer, nullable=False)
    total_cost_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    scenario_factor_id: Mapped[str] = mapped_column(ForeignKey("carbon_factors.id"), nullable=False)
    baseline_factor_id: Mapped[str | None] = mapped_column(ForeignKey("carbon_factors.id"))
    scenario_intensity_dg_per_kwh: Mapped[int] = mapped_column(Integer, nullable=False)
    carbon_diff_dg: Mapped[int | None] = mapped_column(Integer)
    carbon_comparison_status: Mapped[str] = mapped_column(String(32), nullable=False)
    declared_year: Mapped[int] = mapped_column(Integer, nullable=False)
    comparison_gas: Mapped[str] = mapped_column(String(8), nullable=False)
    comparison_boundary: Mapped[str] = mapped_column(String(24), nullable=False)
    baseline_factor_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    scenario_factor_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    score_config_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    score_config_version: Mapped[str] = mapped_column(String(24), nullable=False)
    mode: Mapped[str] = mapped_column(String(24), nullable=False)
    score_total_bp: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_until: Mapped[int] = mapped_column(Integer, nullable=False)
    authorization_signature: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="Offer", nullable=False, index=True)
    reservation_state: Mapped[str] = mapped_column(String(16), default="reserved", nullable=False, index=True)
    failure_reason: Mapped[str | None] = mapped_column(String(80))
    transaction_hash: Mapped[str | None] = mapped_column(String(66), unique=True)
    transaction_from: Mapped[str | None] = mapped_column(String(42))
    transaction_nonce: Mapped[int | None] = mapped_column(Integer)
    chain_id: Mapped[int | None] = mapped_column(Integer)
    block_number: Mapped[int | None] = mapped_column(Integer)
    block_timestamp: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scenario_factor: Mapped[CarbonFactor] = relationship(foreign_keys=[scenario_factor_id])
    baseline_factor: Mapped[CarbonFactor | None] = relationship(foreign_keys=[baseline_factor_id])
