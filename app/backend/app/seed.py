import argparse
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Base, SessionLocal, engine
from app.models import CarbonFactor, EnergyOffer, Participant, TradeRecord

SCENARIO_CODES = {"sunny-day": "SD", "low-generation": "LG", "demand-spike": "DS"}
PARTICIPANTS = [
    ("P1", "Anadolu Solar Co-op", "prosumer", "TR", "solar", "solar_direct_co2", 1),
    ("P2", "Aegean Wind Farm", "prosumer", "TR", "wind", "wind_direct_co2", 2),
    ("P3", "Izmir Microgrid Hub", "prosumer", "TR", "solar", "solar_direct_co2", 3),
    ("P7", "Marmara Grid Supplier", "prosumer", "TR", "grid_mix", "grid_tr_iea2025", 7),
    ("P4", "Ankara Campus", "consumer", "TR", None, None, 4),
    ("P5", "Istanbul Clinic", "consumer", "TR", None, None, 5),
    ("P6", "Berlin Cooperative", "consumer", "DE", None, None, 6),
]
FACTORS = [
    {"id": "solar_direct_co2", "value_dg_per_kwh": 0, "unit": "gCO2/kWh", "region": "GLOBAL", "data_year": None, "edition_year": None, "gas": "CO2", "boundary": "combustion", "factor_use": "rankable", "provenance": "convention", "source_name": "Zero direct combustion emissions for renewables, as in the EEA method", "source_table": None, "source_row": None},
    {"id": "wind_direct_co2", "value_dg_per_kwh": 0, "unit": "gCO2/kWh", "region": "GLOBAL", "data_year": None, "edition_year": None, "gas": "CO2", "boundary": "combustion", "factor_use": "rankable", "provenance": "convention", "source_name": "Zero direct combustion emissions for renewables, as in the EEA method", "source_table": None, "source_row": None},
    {"id": "solar_pv_utility_lifecycle", "value_dg_per_kwh": 480, "unit": "gCO2e/kWh", "region": "GLOBAL", "data_year": None, "edition_year": 2014, "gas": "CO2e", "boundary": "lifecycle", "factor_use": "informational", "provenance": "published", "source_name": "IPCC AR5 WGIII Annex III (median)", "source_table": "Table A.III.2", "source_row": "Utility-scale solar PV"},
    {"id": "wind_onshore_lifecycle", "value_dg_per_kwh": 110, "unit": "gCO2e/kWh", "region": "GLOBAL", "data_year": None, "edition_year": 2014, "gas": "CO2e", "boundary": "lifecycle", "factor_use": "informational", "provenance": "published", "source_name": "IPCC AR5 WGIII Annex III (median)", "source_table": "Table A.III.2", "source_row": "Onshore wind"},
    {"id": "grid_tr_iea2025", "value_dg_per_kwh": 4142, "unit": "gCO2/kWh", "region": "TR", "data_year": 2023, "edition_year": 2025, "gas": "CO2", "boundary": "combustion", "factor_use": "rankable", "provenance": "published", "source_name": "IEA Emissions Factors (2025 edition), via ABB 2025 Electricity Emission Factors", "source_table": "Electricity EF table", "source_row": "Turkiye (TR), Republic of Türkiye"},
]
SCENARIOS = {
    "sunny-day": {
        "sells": [("P1", 500, 9), ("P3", 300, 8), ("P2", 200, 11), ("P7", 400, 14)],
        "buys": [("P4", 200, 15), ("P5", 150, 15), ("P6", 100, 15)],
    },
    "low-generation": {
        "sells": [("P1", 80, 16), ("P3", 60, 15), ("P2", 120, 18), ("P7", 400, 22)],
        "buys": [("P4", 200, 25), ("P5", 150, 25), ("P6", 100, 25)],
    },
    "demand-spike": {
        "sells": [("P1", 300, 12), ("P3", 200, 12), ("P2", 150, 14), ("P7", 600, 19)],
        "buys": [("P4", 500, 30), ("P5", 400, 30), ("P6", 100, 30)],
    },
}


def seed(session: Session, scenario: str = "all", reset: bool = False) -> None:
    selected = list(SCENARIOS) if scenario == "all" else [scenario]
    if reset:
        session.query(TradeRecord).delete(synchronize_session=False)
        session.query(EnergyOffer).delete(synchronize_session=False)
        session.query(Participant).delete(synchronize_session=False)
        session.query(CarbonFactor).delete(synchronize_session=False)
        session.flush()
    if session.scalar(select(Participant.id).limit(1)):
        if reset:
            pass
        else:
            return

    factors = {item["id"]: CarbonFactor(**item, demo_scenario="default_demo", fixture=True, simulated=True) for item in FACTORS}
    session.add_all(factors.values())
    session.flush()
    participants = {}
    participant_base = datetime(2026, 10, 25, 8, tzinfo=timezone.utc)
    for offset, (pid, name, role, region, source, factor_id, wallet_no) in enumerate(PARTICIPANTS):
        p = Participant(
            id=pid,
            display_name=name,
            wallet_address=f"0x{wallet_no:040x}",
            participant_type=role,
            region_code=region,
            default_energy_source=source,
            default_carbon_factor_id=factor_id,
            scenario_id=None,
            created_at=participant_base + timedelta(minutes=offset),
        )
        session.add(p)
        participants[pid] = p
    session.flush()

    expiry = datetime(2030, 12, 31, 23, 59, tzinfo=timezone.utc)
    for scenario_id in selected:
        code = SCENARIO_CODES[scenario_id]
        scenario_rows = SCENARIOS[scenario_id]
        created = datetime(2026, 10, 25, 9, 0, tzinfo=timezone.utc)
        for pid, quantity_kwh, price_cents in scenario_rows["sells"]:
            p = participants[pid]
            session.add(EnergyOffer(
                id=f"L-{code}-{pid}", scenario_id=scenario_id, participant_id=pid, side="sell",
                energy_wh=quantity_kwh * 1000, reserved_wh=0, settled_wh=0,
                price_cents_per_kwh=price_cents, currency="EUR", energy_source=p.default_energy_source,
                carbon_factor_id=p.default_carbon_factor_id, status="active", expires_at=expiry,
                created_at=created,
            ))
            created += timedelta(minutes=1)
        for pid, quantity_kwh, price_ceiling in scenario_rows["buys"]:
            session.add(EnergyOffer(
                id=f"R-{code}-{pid}", scenario_id=scenario_id, participant_id=pid, side="buy",
                energy_wh=quantity_kwh * 1000, reserved_wh=0, settled_wh=0,
                price_cents_per_kwh=price_ceiling, currency="EUR", energy_source=None,
                carbon_factor_id=None, status="active", expires_at=expiry,
                created_at=created,
            ))
            created += timedelta(minutes=1)
    session.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Load deterministic P2P energy demo fixtures.")
    parser.add_argument("--reset", action="store_true", help="Clear demo database state before loading.")
    parser.add_argument("--scenario", choices=[*SCENARIOS, "all"], default="all")
    args = parser.parse_args()
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        seed(session, args.scenario, args.reset)
    print(f"Seeded scenario: {args.scenario}")


if __name__ == "__main__":
    main()
