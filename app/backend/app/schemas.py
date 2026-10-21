from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

PositiveInt = Annotated[StrictInt, Field(gt=0)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]


class ParticipantCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    display_name: str = Field(min_length=2, max_length=160)
    participant_type: Literal["prosumer", "consumer", "both"]
    region_code: str = Field(min_length=2, max_length=8)
    wallet_address: str | None = None
    default_energy_source: str | None = None


class OfferCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    participant_id: str = Field(min_length=1, max_length=80)
    side: Literal["buy", "sell"]
    scenario_id: str = Field(min_length=1, max_length=40)
    energy_wh: PositiveInt
    price_cents_per_kwh: NonNegativeInt
    currency: Literal["EUR"] = "EUR"
    energy_source: str | None = None
    carbon_factor_id: str | None = None
    expires_at: datetime


class MatchPreviewRequest(BaseModel):
    scenario_id: Literal["sunny-day", "low-generation", "demand-spike"]
    mode: Literal["carbon_aware", "price_only"]
    score_config_version: Literal["v1"] = "v1"


class AcceptRequest(BaseModel):
    accept_token: str = Field(min_length=16)
    snapshot_version: str = Field(min_length=16)


class TradePreparationRequest(BaseModel):
    trade_id: str = Field(min_length=1, max_length=120)


class TransactionRegistrationRequest(BaseModel):
    transaction_hash: str = Field(pattern=r"^0x[0-9a-fA-F]{64}$")
