"""Parameter generation for eflips-lca.

This module provides functions to populate ``lca_params`` on eflips-model
entities.  It contains:

- **Working code** to construct and validate the parameter dataclasses from
  given emission-factor values.
- **Placeholder code** showing how to connect to an openLCA IPC server to
  obtain those values automatically.

Prerequisites for openLCA integration::

    pip install olca-ipc
    # An openLCA IPC server must be running with an ecoinvent database.

See ``design_document.md`` sections 3.1-3.4 for the full process mapping.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from eflips.model import BatteryType, EnergySource, VehicleType
from sqlalchemy.orm import Session

from eflips.lca.dataclasses import (
    BatteryTypeLcaParams,
    ChargingPointTypeLcaParams,
    VehicleTypeLcaParams,
)
from eflips.lca.util import DefaultImpactVector

logger = logging.getLogger(__name__)


# ===================================================================
# LCIA method and ecoinvent process mappings
# ===================================================================

LCIA_METHOD_MAPPING: dict[str, str] = {
    "gwp": "IPCC GWP 100a",
    "pm": "Particulate matter formation",
    "pocp": "Photochemical ozone formation",
    "ap": "Acidification",
    "ep_freshwater": "Eutrophication, freshwater",
    "ep_marine": "Eutrophication, marine",
    "fuel": "Fossil resource depletion",
    "water": "Water consumption",
}
"""Mapping from ``DefaultImpactVector`` field names to LCIA method
identifiers in openLCA.  Adjust these to match your database."""

ECOINVENT_PROCESS_MAPPING: dict[str, str] = {
    "lfp_battery_per_kg": "market for battery, Li-ion, LFP, rechargeable",
    "nmc_battery_per_kg": "market for battery, Li-ion, NMC622, rechargeable",
    "electric_motor_per_kg": "market for electric motor, vehicle",
    "chassis_bus_production": "bus production | bus | Cutoff, U",
    "electricity_de_mix": "market for electricity, medium voltage",
    "diesel_production": "market for diesel",
    "diesel_combustion": "diesel, burned in agricultural machinery",
    "maintenance_iceb": "market for maintenance, bus",
    "control_unit": "Tritium_EV_ChargingStation_ControlUnit",
    "power_unit": "Tritium_EV_ChargingStation_PowerUnit",
    "concrete": "market for concrete, normal",
}
"""Mapping from parameter names to ecoinvent process names.

**Notes**:

- ``diesel_combustion`` uses ``diesel, burned in agricultural machinery``
  as a proxy with reference unit 1 MJ.  Multiply by ~45 to convert to
  per-kg (1 kg diesel ~ 45 MJ lower heating value).  A bus-specific
  combustion process should be used if available.
- ``control_unit`` and ``power_unit`` are custom processes created for the
  Tritium charging system architecture.  They must be present in the
  connected openLCA database.
- ``chassis_bus_production`` covers an 11-tonne diesel bus; the diesel
  engine mass is subtracted to obtain per-kg chassis factors.
"""


# ===================================================================
# openLCA placeholder
# ===================================================================


def _query_impact_vector(
    client: Any,
    process_name: str,
    amount: float = 1.0,
) -> DefaultImpactVector:
    """Query openLCA for the impact results of a process.

    .. note::
        This is a **placeholder**.  The actual implementation depends on the
        ``olca-ipc`` API version and the specific openLCA database.

    Implementation guidance::

        import olca_ipc as ipc

        # 1. Find the process
        process = client.find(ipc.Process, process_name)
        if process is None:
            raise RuntimeError(
                f"Process '{process_name}' not found in openLCA"
            )

        # 2. Set up calculation
        setup = ipc.CalculationSetup(target=process, amount=amount)
        result = client.calculate(setup)
        result.wait_until_ready()

        # 3. Extract impact values
        impacts: dict[str, float] = {}
        for field_name, method_name in LCIA_METHOD_MAPPING.items():
            # TODO: Look up the impact category result by method_name
            #       from result.get_total_impacts() or similar.
            impacts[field_name] = 0.0

        result.dispose()
        return DefaultImpactVector(**impacts)

    Args:
        client: An ``olca_ipc.Client`` connected to an openLCA IPC server.
        process_name: The name of the ecoinvent process to query.
        amount: The reference flow amount (default ``1.0``).

    Returns:
        A ``DefaultImpactVector`` populated with the impact results.

    Raises:
        NotImplementedError: Always -- this is a placeholder.
    """
    raise NotImplementedError(
        "openLCA integration not yet implemented. "
        "See docstring and ECOINVENT_PROCESS_MAPPING for guidance."
    )


# ===================================================================
# Working construction helpers
# ===================================================================


def create_vehicle_type_lca_params_beb(
    chassis_ef_per_kg: DefaultImpactVector,
    motor_ef_per_kg: DefaultImpactVector,
    motor_rated_power_kw: float,
    motor_power_to_weight_ratio: float,
    electricity_ef_per_kwh: DefaultImpactVector,
    maintenance_beb_per_year: DefaultImpactVector,
    average_consumption_kwh_per_km: float,
    vehicle_lifetime_years: float = 12.0,
    efficiency_mv_to_lv: float = 0.99,
    efficiency_lv_ac_to_dc: float = 0.95,
) -> VehicleTypeLcaParams:
    """Create LCA parameters for a battery-electric vehicle type.

    Call this with emission-factor values obtained from openLCA (or
    manually from literature).

    Args:
        chassis_ef_per_kg: Chassis emission factors per kg.
        motor_ef_per_kg: Electric motor emission factors per kg.
        motor_rated_power_kw: Rated motor power in kW.
        motor_power_to_weight_ratio: Motor power-to-weight ratio (kW/kg).
        electricity_ef_per_kwh: Grid electricity emission factors per kWh.
        maintenance_beb_per_year: Annual maintenance emissions per vehicle.
        average_consumption_kwh_per_km: Average energy consumption in
            kWh/km for LCA purposes.
        vehicle_lifetime_years: Vehicle lifetime in years (default 12).
        efficiency_mv_to_lv: MV->LV transformer efficiency (default 0.99).
        efficiency_lv_ac_to_dc: AC/DC rectification efficiency
            (default 0.95).

    Returns:
        A validated ``VehicleTypeLcaParams`` for a BEB.
    """
    motor_mass_kg = motor_rated_power_kw / motor_power_to_weight_ratio
    return VehicleTypeLcaParams(
        chassis_emission_factors_per_kg=chassis_ef_per_kg,
        motor_rated_power_kw=motor_rated_power_kw,
        motor_emission_factors_per_kg=motor_ef_per_kg,
        motor_power_to_weight_ratio=motor_power_to_weight_ratio,
        motor_emission_factors_per_unit=None,
        motor_mass_kg=motor_mass_kg,
        vehicle_lifetime_years=vehicle_lifetime_years,
        efficiency_mv_to_lv=efficiency_mv_to_lv,
        efficiency_lv_ac_to_dc=efficiency_lv_ac_to_dc,
        electricity_emission_factors_per_kwh=electricity_ef_per_kwh,
        diesel_emission_factors_production_per_kg=None,
        diesel_emission_factors_combustion_per_kg=None,
        average_consumption_kwh_per_km=average_consumption_kwh_per_km,
        diesel_consumption_kg_per_km=None,
        maintenance_per_year={EnergySource.BATTERY_ELECTRIC: maintenance_beb_per_year},
        energy_source=EnergySource.BATTERY_ELECTRIC,
    )


def create_vehicle_type_lca_params_diesel(
    chassis_ef_per_kg: DefaultImpactVector,
    motor_ef_per_unit: DefaultImpactVector,
    motor_mass_kg: float,
    diesel_ef_production_per_kg: DefaultImpactVector,
    diesel_ef_combustion_per_kg: DefaultImpactVector,
    maintenance_diesel_per_year: DefaultImpactVector,
    average_consumption_kwh_per_km: float,
    diesel_consumption_kg_per_km: float,
    motor_rated_power_kw: float = 0.0,
    vehicle_lifetime_years: float = 12.0,
) -> VehicleTypeLcaParams:
    """Create LCA parameters for a diesel vehicle type.

    Args:
        chassis_ef_per_kg: Chassis emission factors per kg.
        motor_ef_per_unit: Diesel motor emission factors (per complete
            motor).
        motor_mass_kg: Diesel motor mass in kg (default 1900).
        diesel_ef_production_per_kg: Well-to-tank emissions per kg diesel.
        diesel_ef_combustion_per_kg: Tank-to-wheel emissions per kg diesel.
        maintenance_diesel_per_year: Annual maintenance emissions per
            vehicle.
        average_consumption_kwh_per_km: Average energy consumption in
            kWh/km (for comparability; not used in diesel energy calc).
        diesel_consumption_kg_per_km: Diesel consumption in kg/km.
        motor_rated_power_kw: Rated motor power in kW (informational).
        vehicle_lifetime_years: Vehicle lifetime in years (default 12).

    Returns:
        A validated ``VehicleTypeLcaParams`` for an ICEB.
    """
    return VehicleTypeLcaParams(
        chassis_emission_factors_per_kg=chassis_ef_per_kg,
        motor_rated_power_kw=motor_rated_power_kw,
        motor_emission_factors_per_kg=None,
        motor_power_to_weight_ratio=None,
        motor_emission_factors_per_unit=motor_ef_per_unit,
        motor_mass_kg=motor_mass_kg,
        vehicle_lifetime_years=vehicle_lifetime_years,
        efficiency_mv_to_lv=None,
        efficiency_lv_ac_to_dc=None,
        electricity_emission_factors_per_kwh=None,
        diesel_emission_factors_production_per_kg=diesel_ef_production_per_kg,
        diesel_emission_factors_combustion_per_kg=diesel_ef_combustion_per_kg,
        average_consumption_kwh_per_km=average_consumption_kwh_per_km,
        diesel_consumption_kg_per_km=diesel_consumption_kg_per_km,
        maintenance_per_year={EnergySource.DIESEL: maintenance_diesel_per_year},
        energy_source=EnergySource.DIESEL,
    )


def create_battery_type_lca_params(
    emission_factors_per_kg: DefaultImpactVector,
    battery_lifetime_years: float = 8.0,
) -> BatteryTypeLcaParams:
    """Create LCA parameters for a battery type.

    Args:
        emission_factors_per_kg: Prod+EoL emissions per kg of battery
            pack.
        battery_lifetime_years: Battery lifetime for LCA amortisation
            (default 8).

    Returns:
        A ``BatteryTypeLcaParams``.
    """
    return BatteryTypeLcaParams(
        emission_factors_per_kg=emission_factors_per_kg,
        battery_lifetime_years=battery_lifetime_years,
    )


def create_charging_point_type_lca_params(
    control_unit_emissions: DefaultImpactVector,
    power_unit_emissions_per_kg: DefaultImpactVector,
    power_unit_mass_kg: float,
    power_unit_rated_power_kw: float,
    user_unit_emissions_per_kg: DefaultImpactVector,
    user_unit_mass_kg: float,
    concrete_emissions_per_m3: DefaultImpactVector,
    foundation_volume_per_point_m3: float = 3.96,
    infrastructure_lifetime_years: float = 20.0,
) -> ChargingPointTypeLcaParams:
    """Create LCA parameters for a charging point type.

    Args:
        control_unit_emissions: Per-unit emissions for one control unit.
        power_unit_emissions_per_kg: Per-kg emissions for the power unit.
        power_unit_mass_kg: Mass of one power unit in kg.
        power_unit_rated_power_kw: Rated power of one power unit in kW.
        user_unit_emissions_per_kg: Per-kg emissions for the user unit.
        user_unit_mass_kg: Mass of one user unit in kg.
        concrete_emissions_per_m3: Per-m3 emissions for concrete
            foundation.
        foundation_volume_per_point_m3: Concrete volume per charging
            point in m3 (default 3.96).
        infrastructure_lifetime_years: Lifetime for amortisation
            (default 20).

    Returns:
        A ``ChargingPointTypeLcaParams``.
    """
    return ChargingPointTypeLcaParams(
        control_unit_emissions=control_unit_emissions,
        power_unit_emissions_per_kg=power_unit_emissions_per_kg,
        power_unit_mass_kg=power_unit_mass_kg,
        power_unit_rated_power_kw=power_unit_rated_power_kw,
        user_unit_emissions_per_kg=user_unit_emissions_per_kg,
        user_unit_mass_kg=user_unit_mass_kg,
        concrete_emissions_per_m3=concrete_emissions_per_m3,
        foundation_volume_per_point_m3=foundation_volume_per_point_m3,
        infrastructure_lifetime_years=infrastructure_lifetime_years,
    )


# ===================================================================
# Full populate workflow placeholder
# ===================================================================


def populate_lca_params(
    session: Session,
    vehicle_type: VehicleType,
    battery_type: BatteryType | None,
    ipc_client: Any,
) -> None:
    """Populate ``lca_params`` on eflips-model entities via openLCA.

    .. note::
        This is a **placeholder**.  Implement each step using
        ``_query_impact_vector`` once the openLCA integration is ready.

    Workflow (see ``design_document.md`` §3.3):

    1. **Chassis**: Query ``bus production | bus | Cutoff, U`` from
       ecoinvent.  Subtract the diesel engine contribution, then divide
       by the reference bus mass to get per-kg factors.

    2. **Motor**:

       - *BEB*: Query ``market for electric motor, vehicle`` for per-kg
         factors.
       - *ICEB*: Assemble a custom process from aluminium (2%),
         polyethylene (9%), and steel (89%) production processes,
         weighted by mass fraction of a 1900 kg motor.

    3. **Battery** (if ``battery_type`` is set): Determine chemistry
       from ``battery_type.chemistry`` (e.g. ``"LFP"`` or ``"NMC622"``).
       Query the matching ``market for battery, Li-ion, ...`` process.

    4. **Electricity** (BEB): Query
       ``market for electricity, medium voltage`` for the German mix.

    5. **Diesel** (ICEB): Query ``market for diesel`` (well-to-tank)
       and ``diesel, burned in agricultural machinery`` (tank-to-wheel,
       scale x45 from 1 MJ to 1 kg).

    6. **Maintenance**: Query ``market for maintenance, bus``.  For BEB
       apply a literature-based reduction factor (~0.75).

    7. **Charging infrastructure**: Query the custom Tritium processes
       for control unit and power unit.

    8. **Assemble**: Use the ``create_*`` helpers above to construct the
       parameter dataclasses, then write back via::

           vehicle_type.lca_params = params.to_dict()
           if battery_type is not None:
               battery_type.lca_params = bt_params.to_dict()
           session.flush()

    Args:
        session: SQLAlchemy session.
        vehicle_type: The vehicle type to populate.
        battery_type: The battery type to populate, or ``None``.
        ipc_client: An ``olca_ipc.Client`` instance.

    Raises:
        NotImplementedError: Always -- this is a placeholder.
    """
    # TODO: Implement each step above using _query_impact_vector().
    #       Check for custom processes and raise clear errors if missing.
    raise NotImplementedError(
        "Full openLCA populate workflow not yet implemented. "
        "See docstring for step-by-step guidance."
    )
