# eflips-lca

Life Cycle Assessment for eFLIPS electric and diesel bus fleet simulations, following ISO 14040/14044. Functional unit: revenue-kilometre (Nutzwagenkilometer).

## Project layout

```
eflips/lca/
  __init__.py              # Public API re-exports
  util.py                  # ImpactVector / DefaultImpactVector (8-category dataclass with generic arithmetic)
  dataclasses.py           # VehicleTypeLcaParams, BatteryTypeLcaParams, ChargingPointTypeLcaParams, LcaResult
  extraction.py            # Queries eflips-model DB for vehicle-km, revenue-km, fleet size, peak charging
  calculation.py           # LCA formulas: production+EoL, use phase, charging infrastructure
  parameter_generation.py  # Helpers to build param dataclasses + openLCA placeholder
EFLIPS_MODEL_CHANGES.md    # Instructions for adding lca_params JSONB columns to eflips-model
design_document.md         # Full methodology and formulas
```

## How it works

1. **Parameters** (`lca_params` JSONB on `VehicleType`, `BatteryType`, `ChargingPointType`) hold emission factors and physical constants. These don't exist in eflips-model yet — see `EFLIPS_MODEL_CHANGES.md`.
2. **Extraction** (`extraction.py`) queries an eflips-model database for simulation outputs: vehicle-km, revenue-km, `n_ready`, peak charging power/occupancy. Energy/diesel consumption is *not* extracted from events — it's computed from `average_consumption_kwh_per_km` (or `diesel_consumption_kg_per_km`) in lca_params times vehicle-km, because LCA uses average consumption, not worst-case simulation values.
3. **Calculation** (`calculation.py`) implements three lifecycle phases:
   - **Production+EoL**: chassis (mass-based), motor (mass or per-unit), battery (mass-based), amortised over lifetimes, normalised by revenue-km
   - **Use phase**: electricity (efficiency chain through MV→LV→AC/DC→battery) or diesel (well-to-tank + tank-to-wheel), plus maintenance
   - **Charging infrastructure** (BEB only): depot areas + terminal stations, using `power_and_occupancy()` from eflips-eval
4. **Result** is an `LcaResult` with per-revenue-km `DefaultImpactVector`s broken down by contributor and vehicle type.

## Key dependencies

- `eflips-model` — ORM classes (`VehicleType`, `BatteryType`, `Area`, `Station`, etc.)
- `eflips-eval` — `power_and_occupancy()` for peak charging power/occupancy extraction
- `EnergySource` enum from `eflips.model` is used as dict key type in `maintenance_per_year`

## Development rules

- `poetry` is in use. If your `python` in the $PATH looks weird, run `$(poetry env activate)`. Current venv is Python 3.13 (constraint `>=3.10,<3.14`).
- Code formatted with `black`
- All code must have type annotations and pass `mypy eflips --explicit-package-bases --strict`
- All methods need a Google-Style (markdown) docstring
- All code has tests using `pytest`
