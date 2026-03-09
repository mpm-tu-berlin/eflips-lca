"""Intermediate openLCA data layer for eflips-lca.

Provides the ``OpenLcaData`` dataclass that captures all openLCA-derived
emission factors and scalar parameters, serializes to/from JSON, and
supports year-specific electricity emission factors with interpolation.

Data flow::

    openLCA (offline) --> bin/export_openlca.py --> data/*.json (git-tracked)
                                                         |
                                          populate_lca_params_from_file()
                                                         |
                                          lca_params JSONB on eflips-model
                                                         |
                                          calculation.py (unchanged)
"""

from __future__ import annotations

import dataclasses
import json
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_type_hints

from sqlalchemy.orm import Session

from eflips.model import EnergySource

from eflips.lca.dataclasses import (
    BatteryTypeLcaParams,
    ChargingPointTypeLcaParams,
    VehicleTypeLcaParams,
)
from eflips.lca.util import DefaultImpactVector

# ===================================================================
# YearSeries
# ===================================================================


@dataclass
class YearSeries:
    """Year-indexed series of ``DefaultImpactVector`` values.

    Maps calendar years to impact vectors, with linear interpolation
    for years between defined data points and clamping (with a warning)
    for years outside the defined range.

    Attributes:
        data: Mapping from calendar year to ``DefaultImpactVector``.
    """

    data: dict[int, DefaultImpactVector]

    def at_year(self, year: int) -> DefaultImpactVector:
        """Look up or interpolate an impact vector for a given year.

        Args:
            year: The calendar year to query.

        Returns:
            The exact or interpolated ``DefaultImpactVector``.

        Raises:
            ValueError: If the series is empty.
        """
        if not self.data:
            raise ValueError("YearSeries is empty")

        if year in self.data:
            return self.data[year]

        sorted_years = sorted(self.data.keys())

        if year < sorted_years[0]:
            warnings.warn(
                f"Year {year} is before the earliest data point "
                f"({sorted_years[0]}), clamping.",
                stacklevel=2,
            )
            return self.data[sorted_years[0]]

        if year > sorted_years[-1]:
            warnings.warn(
                f"Year {year} is after the latest data point "
                f"({sorted_years[-1]}), clamping.",
                stacklevel=2,
            )
            return self.data[sorted_years[-1]]

        # Linear interpolation between two surrounding years
        lo_year = max(y for y in sorted_years if y <= year)
        hi_year = min(y for y in sorted_years if y >= year)
        t = (year - lo_year) / (hi_year - lo_year)
        iv_lo = self.data[lo_year]
        iv_hi = self.data[hi_year]
        return iv_lo * (1.0 - t) + iv_hi * t

    def to_dict(self) -> dict[str, dict[str, float]]:
        """Serialize to a JSON-compatible dict with string year keys.

        Returns:
            A dict mapping year strings to impact vector dicts.
        """
        return {str(year): iv.to_dict() for year, iv in self.data.items()}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> YearSeries:
        """Deserialize from a dict with string year keys.

        Args:
            raw: A dict mapping year strings to impact vector dicts.

        Returns:
            A ``YearSeries`` instance.
        """
        data = {
            int(year_str): DefaultImpactVector.from_dict(iv_dict)
            for year_str, iv_dict in raw.items()
        }
        return cls(data=data)


# ===================================================================
# OpenLcaData
# ===================================================================


@dataclass
class OpenLcaData:
    """All openLCA-derived emission factors and scalar parameters.

    Captures the 14 ImpactVectors from openLCA plus scalar/literature
    parameters needed to populate ``lca_params`` on eflips-model entities.

    Attributes:
        ecoinvent_version: Version string for the ecoinvent database.
        lcia_method_set: Name/version of the LCIA method set used.
        description: Free-text description of this dataset.
        created_at: ISO 8601 timestamp of creation.
        chassis_per_kg: Chassis emission factors per kg.
        electric_motor_per_kg: Electric motor emission factors per kg.
        diesel_motor_per_unit: Diesel motor emission factors per unit.
        lfp_battery_per_kg: LFP battery emission factors per kg.
        nmc_battery_per_kg: NMC battery emission factors per kg.
        electricity_per_kwh: Year-varying electricity emission factors
            per kWh.
        diesel_production_per_kg: Diesel well-to-tank emission factors
            per kg.
        diesel_combustion_per_kg: Diesel tank-to-wheel emission factors
            per kg (already scaled x45).
        maintenance_iceb_per_year: ICEB maintenance emission factors
            per bus-year.
        maintenance_beb_per_year: BEB maintenance emission factors
            per bus-year.
        control_unit: Charging control unit emission factors per unit.
        power_unit_per_kg: Charging power unit emission factors per kg.
        user_unit_per_kg: Charging user unit emission factors per kg.
        concrete_per_m3: Concrete emission factors per m3.
        motor_power_to_weight_ratio_kw_per_kg: Electric motor kW/kg.
        diesel_motor_mass_kg: Diesel motor mass in kg.
        vehicle_lifetime_years: Vehicle lifetime for amortisation.
        efficiency_mv_to_lv: MV to LV transformer efficiency.
        efficiency_lv_ac_to_dc: AC/DC rectification efficiency.
        battery_lifetime_years: Battery lifetime for amortisation.
        beb_maintenance_reduction_factor: BEB maintenance reduction
            factor relative to ICEB (stored for traceability; the
            already-reduced value is in ``maintenance_beb_per_year``).
        power_unit_mass_kg: Mass of one power unit in kg.
        power_unit_rated_power_kw: Rated power of one power unit in kW.
        user_unit_mass_kg: Mass of one user unit in kg.
        foundation_volume_per_point_m3: Concrete volume per charging
            point in m3.
        infrastructure_lifetime_years: Charging infrastructure lifetime.
    """

    # Metadata
    ecoinvent_version: str
    lcia_method_set: str
    description: str
    created_at: str

    # 14 emission factor ImpactVectors
    chassis_per_kg: DefaultImpactVector
    electric_motor_per_kg: DefaultImpactVector
    diesel_motor_per_unit: DefaultImpactVector
    lfp_battery_per_kg: DefaultImpactVector
    nmc_battery_per_kg: DefaultImpactVector
    electricity_per_kwh: YearSeries
    diesel_production_per_kg: DefaultImpactVector
    diesel_combustion_per_kg: DefaultImpactVector
    maintenance_iceb_per_year: DefaultImpactVector
    maintenance_beb_per_year: DefaultImpactVector
    control_unit: DefaultImpactVector
    power_unit_per_kg: DefaultImpactVector
    user_unit_per_kg: DefaultImpactVector
    concrete_per_m3: DefaultImpactVector

    # Scalar / literature parameters
    motor_power_to_weight_ratio_kw_per_kg: float
    diesel_motor_mass_kg: float = 1900.0
    vehicle_lifetime_years: float = 12.0
    efficiency_mv_to_lv: float = 0.99
    efficiency_lv_ac_to_dc: float = 0.95
    battery_lifetime_years: float = 8.0
    beb_maintenance_reduction_factor: float = 0.75
    power_unit_mass_kg: float = 700.0
    power_unit_rated_power_kw: float = 150.0
    user_unit_mass_kg: float = 20.0
    foundation_volume_per_point_m3: float = 3.96
    infrastructure_lifetime_years: float = 20.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict.

        Dispatches by resolved type annotation: ``str`` and ``float``
        fields pass through; ``DefaultImpactVector`` and ``YearSeries``
        fields delegate to their own ``to_dict()``.

        Returns:
            A dict suitable for ``json.dumps()``.
        """
        hints = get_type_hints(type(self))
        result: dict[str, Any] = {}
        for f in dataclasses.fields(self):
            value = getattr(self, f.name)
            hint = hints[f.name]
            if hint is str or hint is float:
                result[f.name] = value
            elif hint is DefaultImpactVector or hint is YearSeries:
                result[f.name] = value.to_dict()
            else:
                raise TypeError(f"Unsupported field type {hint!r} for field '{f.name}'")
        return result

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> OpenLcaData:
        """Deserialize from a dict.

        Dispatches by resolved type annotation. Scalar ``float`` fields
        fall back to dataclass defaults when absent from *raw*.

        Args:
            raw: A dict as produced by ``to_dict()``.

        Returns:
            An ``OpenLcaData`` instance.
        """
        hints = get_type_hints(cls)
        kwargs: dict[str, Any] = {}
        for f in dataclasses.fields(cls):
            hint = hints[f.name]
            if hint is str:
                kwargs[f.name] = str(raw[f.name])
            elif hint is float:
                default = f.default
                if default is not dataclasses.MISSING:
                    kwargs[f.name] = float(raw.get(f.name, default))
                else:
                    kwargs[f.name] = float(raw[f.name])
            elif hint is DefaultImpactVector:
                kwargs[f.name] = DefaultImpactVector.from_dict(raw[f.name])
            elif hint is YearSeries:
                kwargs[f.name] = YearSeries.from_dict(raw[f.name])
            else:
                raise TypeError(f"Unsupported field type {hint!r} for field '{f.name}'")
        return cls(**kwargs)

    def to_json(self, path: str | Path) -> None:
        """Write this dataset to a JSON file.

        Args:
            path: File path to write to.
        """
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, path: str | Path) -> OpenLcaData:
        """Load a dataset from a JSON file.

        Args:
            path: File path to read from.

        Returns:
            An ``OpenLcaData`` instance.
        """
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return cls.from_dict(raw)


# ===================================================================
# VehicleTypeOverrides
# ===================================================================


@dataclass
class VehicleTypeOverrides:
    """Per-vehicle-type values not from openLCA.

    These differ per bus model and must be provided alongside the
    ``OpenLcaData`` when populating ``lca_params``.

    Attributes:
        motor_rated_power_kw: Rated motor power in kW.
        average_consumption_kwh_per_km: Average energy consumption
            in kWh/km for LCA.
        diesel_consumption_kg_per_km: Average diesel consumption in
            kg/km, or ``None`` for BEB.
    """

    motor_rated_power_kw: float
    average_consumption_kwh_per_km: float
    diesel_consumption_kg_per_km: float | None = None


# ===================================================================
# Parameter construction helpers
# ===================================================================


def _create_vehicle_type_lca_params_beb(
    chassis_ef_per_kg: DefaultImpactVector,
    motor_ef_per_kg: DefaultImpactVector,
    motor_rated_power_kw: float,
    motor_power_to_weight_ratio: float,
    electricity_ef_per_kwh: DefaultImpactVector,
    maintenance_beb_per_year: DefaultImpactVector,
    average_consumption_kwh_per_km: float,
    vehicle_lifetime_years: float,
    efficiency_mv_to_lv: float,
    efficiency_lv_ac_to_dc: float,
) -> VehicleTypeLcaParams:
    """Create LCA parameters for a battery-electric vehicle type.

    Args:
        chassis_ef_per_kg: Chassis emission factors per kg.
        motor_ef_per_kg: Electric motor emission factors per kg.
        motor_rated_power_kw: Rated motor power in kW.
        motor_power_to_weight_ratio: Motor power-to-weight ratio (kW/kg).
        electricity_ef_per_kwh: Grid electricity emission factors per kWh.
        maintenance_beb_per_year: Annual maintenance emissions per vehicle.
        average_consumption_kwh_per_km: Average energy consumption in
            kWh/km for LCA purposes.
        vehicle_lifetime_years: Vehicle lifetime in years.
        efficiency_mv_to_lv: MV->LV transformer efficiency.
        efficiency_lv_ac_to_dc: AC/DC rectification efficiency.

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


def _create_vehicle_type_lca_params_diesel(
    chassis_ef_per_kg: DefaultImpactVector,
    motor_ef_per_unit: DefaultImpactVector,
    motor_mass_kg: float,
    diesel_ef_production_per_kg: DefaultImpactVector,
    diesel_ef_combustion_per_kg: DefaultImpactVector,
    maintenance_diesel_per_year: DefaultImpactVector,
    average_consumption_kwh_per_km: float,
    diesel_consumption_kg_per_km: float,
    motor_rated_power_kw: float,
    vehicle_lifetime_years: float,
) -> VehicleTypeLcaParams:
    """Create LCA parameters for a diesel vehicle type.

    Args:
        chassis_ef_per_kg: Chassis emission factors per kg.
        motor_ef_per_unit: Diesel motor emission factors (per complete
            motor).
        motor_mass_kg: Diesel motor mass in kg.
        diesel_ef_production_per_kg: Well-to-tank emissions per kg diesel.
        diesel_ef_combustion_per_kg: Tank-to-wheel emissions per kg diesel.
        maintenance_diesel_per_year: Annual maintenance emissions per
            vehicle.
        average_consumption_kwh_per_km: Average energy consumption in
            kWh/km (for comparability; not used in diesel energy calc).
        diesel_consumption_kg_per_km: Diesel consumption in kg/km.
        motor_rated_power_kw: Rated motor power in kW.
        vehicle_lifetime_years: Vehicle lifetime in years.

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


def _create_battery_type_lca_params(
    emission_factors_per_kg: DefaultImpactVector,
    battery_lifetime_years: float,
) -> BatteryTypeLcaParams:
    """Create LCA parameters for a battery type.

    Args:
        emission_factors_per_kg: Prod+EoL emissions per kg of battery
            pack.
        battery_lifetime_years: Battery lifetime for LCA amortisation.

    Returns:
        A ``BatteryTypeLcaParams``.
    """
    return BatteryTypeLcaParams(
        emission_factors_per_kg=emission_factors_per_kg,
        battery_lifetime_years=battery_lifetime_years,
    )


def _create_charging_point_type_lca_params(
    control_unit_emissions: DefaultImpactVector,
    power_unit_emissions_per_kg: DefaultImpactVector,
    power_unit_mass_kg: float,
    power_unit_rated_power_kw: float,
    user_unit_emissions_per_kg: DefaultImpactVector,
    user_unit_mass_kg: float,
    concrete_emissions_per_m3: DefaultImpactVector,
    foundation_volume_per_point_m3: float,
    infrastructure_lifetime_years: float,
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
            point in m3.
        infrastructure_lifetime_years: Lifetime for amortisation.

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
# Population functions
# ===================================================================


def populate_lca_params_from_data(
    session: Session,
    scenario_id: int,
    open_lca_data: OpenLcaData,
    year: int,
    vehicle_type_overrides: dict[int, VehicleTypeOverrides],
) -> None:
    """Populate ``lca_params`` on eflips-model entities from an ``OpenLcaData``.

    Builds ``VehicleTypeLcaParams``, ``BatteryTypeLcaParams``, and
    ``ChargingPointTypeLcaParams`` and writes the resulting dicts to the
    JSONB columns.

    Args:
        session: SQLAlchemy session connected to an eflips-model database.
        scenario_id: ID of the scenario whose entities to populate.
        open_lca_data: The openLCA dataset.
        year: Calendar year for year-specific values (electricity mix).
        vehicle_type_overrides: Per-vehicle-type overrides, keyed by
            ``VehicleType.id``.
    """
    from eflips.model import BatteryType, ChargingPointType, VehicleType

    d = open_lca_data
    electricity_iv = d.electricity_per_kwh.at_year(year)

    # --- VehicleTypes ---
    vehicle_types = (
        session.query(VehicleType).filter(VehicleType.scenario_id == scenario_id).all()
    )
    for vtype in vehicle_types:
        vtype_id = int(vtype.id)
        if vtype_id not in vehicle_type_overrides:
            continue
        ovr = vehicle_type_overrides[vtype_id]

        if vtype.energy_source == EnergySource.BATTERY_ELECTRIC:
            params = _create_vehicle_type_lca_params_beb(
                chassis_ef_per_kg=d.chassis_per_kg,
                motor_ef_per_kg=d.electric_motor_per_kg,
                motor_rated_power_kw=ovr.motor_rated_power_kw,
                motor_power_to_weight_ratio=d.motor_power_to_weight_ratio_kw_per_kg,
                electricity_ef_per_kwh=electricity_iv,
                maintenance_beb_per_year=d.maintenance_beb_per_year,
                average_consumption_kwh_per_km=ovr.average_consumption_kwh_per_km,
                vehicle_lifetime_years=d.vehicle_lifetime_years,
                efficiency_mv_to_lv=d.efficiency_mv_to_lv,
                efficiency_lv_ac_to_dc=d.efficiency_lv_ac_to_dc,
            )
        elif vtype.energy_source == EnergySource.DIESEL:
            if ovr.diesel_consumption_kg_per_km is None:
                raise ValueError(
                    f"VehicleType {vtype_id}: diesel_consumption_kg_per_km "
                    f"required for DIESEL"
                )
            params = _create_vehicle_type_lca_params_diesel(
                chassis_ef_per_kg=d.chassis_per_kg,
                motor_ef_per_unit=d.diesel_motor_per_unit,
                motor_mass_kg=d.diesel_motor_mass_kg,
                diesel_ef_production_per_kg=d.diesel_production_per_kg,
                diesel_ef_combustion_per_kg=d.diesel_combustion_per_kg,
                maintenance_diesel_per_year=d.maintenance_iceb_per_year,
                average_consumption_kwh_per_km=ovr.average_consumption_kwh_per_km,
                diesel_consumption_kg_per_km=ovr.diesel_consumption_kg_per_km,
                motor_rated_power_kw=ovr.motor_rated_power_kw,
                vehicle_lifetime_years=d.vehicle_lifetime_years,
            )
        else:
            raise ValueError(f"Unsupported energy source: {vtype.energy_source}")

        vtype.lca_params = params.to_dict()

    # --- BatteryTypes ---
    battery_types = (
        session.query(BatteryType).filter(BatteryType.scenario_id == scenario_id).all()
    )
    for bt in battery_types:
        chemistry = getattr(bt, "chemistry", None)
        if chemistry is not None and str(chemistry).upper().startswith("NMC"):
            ef = d.nmc_battery_per_kg
        else:
            ef = d.lfp_battery_per_kg
        bt_params = _create_battery_type_lca_params(
            emission_factors_per_kg=ef,
            battery_lifetime_years=d.battery_lifetime_years,
        )
        bt.lca_params = bt_params.to_dict()

    # --- ChargingPointTypes ---
    charging_point_types = (
        session.query(ChargingPointType)
        .filter(ChargingPointType.scenario_id == scenario_id)
        .all()
    )
    for cpt in charging_point_types:
        cpt_params = _create_charging_point_type_lca_params(
            control_unit_emissions=d.control_unit,
            power_unit_emissions_per_kg=d.power_unit_per_kg,
            power_unit_mass_kg=d.power_unit_mass_kg,
            power_unit_rated_power_kw=d.power_unit_rated_power_kw,
            user_unit_emissions_per_kg=d.user_unit_per_kg,
            user_unit_mass_kg=d.user_unit_mass_kg,
            concrete_emissions_per_m3=d.concrete_per_m3,
            foundation_volume_per_point_m3=d.foundation_volume_per_point_m3,
            infrastructure_lifetime_years=d.infrastructure_lifetime_years,
        )
        cpt.lca_params = cpt_params.to_dict()

    session.flush()


def populate_lca_params_from_file(
    session: Session,
    scenario_id: int,
    json_path: str | Path,
    year: int,
    vehicle_type_overrides: dict[int, VehicleTypeOverrides],
) -> None:
    """Populate ``lca_params`` from a JSON file.

    Convenience wrapper that loads the JSON first, then delegates to
    ``populate_lca_params_from_data``.

    Args:
        session: SQLAlchemy session connected to an eflips-model database.
        scenario_id: ID of the scenario whose entities to populate.
        json_path: Path to the openLCA data JSON file.
        year: Calendar year for year-specific values.
        vehicle_type_overrides: Per-vehicle-type overrides, keyed by
            ``VehicleType.id``.
    """
    data = OpenLcaData.from_json(json_path)
    populate_lca_params_from_data(
        session, scenario_id, data, year, vehicle_type_overrides
    )
