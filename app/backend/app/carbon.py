import json
from typing import Any

from eth_utils import keccak

from app.models import CarbonFactor

RANKING_BASIS = {"gas": "CO2", "boundary": "combustion"}


def canonical_hash(payload: dict[str, Any]) -> str:
    """Hash integer-only JCS-compatible objects (all hash inputs avoid floats)."""
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "0x" + keccak(encoded).hex()


def factor_hash_payload(factor: CarbonFactor) -> dict[str, Any]:
    return {
        "hash_schema": "climate-factor/1",
        "id": factor.id,
        "value_dg": factor.value_dg_per_kwh,
        "unit": factor.unit,
        "region": factor.region,
        "data_year": factor.data_year,
        "gas": factor.gas,
        "boundary": factor.boundary,
        "source_name": factor.source_name,
    }


def factor_hash(factor: CarbonFactor) -> str:
    return canonical_hash(factor_hash_payload(factor))


def factor_public(factor: CarbonFactor | None) -> dict[str, Any] | None:
    if factor is None:
        return None
    return {
        "id": factor.id,
        "value": factor.value_dg_per_kwh / 10,
        "value_dg_per_kwh": factor.value_dg_per_kwh,
        "unit": factor.unit,
        "region": factor.region,
        "data_year": factor.data_year,
        "edition_year": factor.edition_year,
        "demo_scenario": factor.demo_scenario,
        "comparison_basis": {"gas": factor.gas, "boundary": factor.boundary},
        "use": factor.factor_use,
        "provenance": factor.provenance,
        "fixture": factor.fixture,
        "simulated": factor.simulated,
        "source": {"name": factor.source_name, "table": factor.source_table, "row": factor.source_row},
        "factor_hash": factor_hash(factor),
    }


def comparison(buyer_region: str, scenario: CarbonFactor, baseline_by_region: dict[str, CarbonFactor], energy_wh: int):
    baseline = baseline_by_region.get(buyer_region)
    same_basis = scenario.gas == RANKING_BASIS["gas"] and scenario.boundary == RANKING_BASIS["boundary"]
    comparable = (
        baseline is not None
        and same_basis
        and baseline.gas == scenario.gas
        and baseline.boundary == scenario.boundary
        and baseline.factor_use == "rankable"
        and scenario.factor_use == "rankable"
    )
    if not same_basis or (baseline is not None and (baseline.gas != scenario.gas or baseline.boundary != scenario.boundary)):
        status = "basis_mismatch"
    elif baseline is None:
        status = "baseline_unavailable"
    else:
        status = "comparable" if comparable else "basis_mismatch"
    difference = None
    if comparable:
        # Signed integer arithmetic exactly matches Solidity division truncation.
        difference = (energy_wh * (baseline.value_dg_per_kwh - scenario.value_dg_per_kwh)) // 1000
        if energy_wh * (baseline.value_dg_per_kwh - scenario.value_dg_per_kwh) < 0:
            difference = -((-energy_wh * (baseline.value_dg_per_kwh - scenario.value_dg_per_kwh)) // 1000)
    return baseline, status, difference


def score_config_payload(mode: str, applied_weights: dict[str, int]) -> dict[str, Any]:
    configured = {"carbon": 4000, "price": 3000, "quantity_fit": 3000} if mode == "carbon_aware" else {
        "carbon": 0, "price": 5000, "quantity_fit": 5000
    }
    return {
        "hash_schema": "climate-score-config/1",
        "score_config_version": "v1",
        "mode": mode,
        "weights_configured_bp": configured,
        "weights_applied_bp": applied_weights,
        "ranges": {"carbon_dg_per_kwh": [0, 10000], "price_cents_per_kwh": [0, 100], "quantity_fit_bp": [0, 10000]},
        "normalization": "fixed_range_clamped",
        "score_decimals": 4,
        "tie_break": ["score_desc", "price_asc", "created_at_asc", "id_asc"],
    }


def score_config_hash(mode: str, applied_weights: dict[str, int]) -> str:
    return canonical_hash(score_config_payload(mode, applied_weights))
