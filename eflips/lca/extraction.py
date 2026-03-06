"""Extract simulation outputs from an eflips-model database.

Queries an eflips-model database for vehicle kilometres, revenue
kilometres, fleet size, and peak charging infrastructure utilisation.
Energy and diesel consumption are computed in the calculation step from
``lca_params`` values and the kilometres extracted here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable

import sqlalchemy
from eflips.eval.output.prepare import power_and_occupancy
from eflips.model import (
    Area,
    Depot,
    EnergySource,
    Rotation,
    Station,
    Trip,
    TripType,
    VehicleType,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class VehicleTypeSimData:
    """Extracted simulation data for one vehicle type.

    Attributes:
        vehicle_type_id: The ``VehicleType`` primary key.
        annual_vehicle_kilometers: Total vehicle-km (all trips), annualised.
        annual_revenue_kilometers: Total revenue vehicle-km (passenger trips
            only), annualised.
        n_ready: Number of operationally ready vehicles (distinct vehicles
            used in rotations).
    """

    vehicle_type_id: int
    annual_vehicle_kilometers: float
    annual_revenue_kilometers: float
    n_ready: int


@dataclass
class AreaSimData:
    """Extracted simulation data for one depot charging area.

    Attributes:
        area_id: The ``Area`` primary key.
        peak_charging_power_kw: Maximum simultaneous charging power in kW.
        peak_simultaneous_vehicles: Maximum number of vehicles present at
            the same time.
    """

    area_id: int
    peak_charging_power_kw: float
    peak_simultaneous_vehicles: int


@dataclass
class StationSimData:
    """Extracted simulation data for one terminal station.

    Attributes:
        station_id: The ``Station`` primary key.
        peak_charging_power_kw: Maximum simultaneous charging power in kW.
        peak_simultaneous_vehicles: Maximum number of vehicles present at
            the same time.
    """

    station_id: int
    peak_charging_power_kw: float
    peak_simultaneous_vehicles: int


@dataclass
class ScenarioSimData:
    """All extracted simulation data for a scenario.

    Attributes:
        vehicle_type_data: Per-vehicle-type data, keyed by
            ``VehicleType.id``.
        area_data: Per-area data, keyed by ``Area.id``.
        station_data: Per-station data, keyed by ``Station.id``.
        eta_avail: Technical availability factor.
    """

    vehicle_type_data: dict[int, VehicleTypeSimData] = field(default_factory=dict)
    area_data: dict[int, AreaSimData] = field(default_factory=dict)
    station_data: dict[int, StationSimData] = field(default_factory=dict)
    eta_avail: float = 0.9


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _annual_scaling_factor(sim_start_time: datetime, sim_end_time: datetime) -> float:
    """Compute the factor to scale simulation-period values to annual.

    Args:
        sim_start_time: Simulation window start.
        sim_end_time: Simulation window end.

    Returns:
        ``365 / sim_duration_days``.

    Raises:
        ValueError: If the simulation window is non-positive.
    """
    duration = sim_end_time - sim_start_time
    duration_days = duration.total_seconds() / 86_400.0
    if duration_days <= 0:
        raise ValueError(
            f"sim_end_time must be after sim_start_time, got duration " f"{duration}"
        )
    return 365.0 / duration_days


def _extract_kilometres(
    session: Session,
    scenario_id: int,
    sim_start_time: datetime,
    sim_end_time: datetime,
    scaling: float,
) -> dict[int, tuple[float, float]]:
    """Query vehicle-km and revenue-km per vehicle type.

    Args:
        session: SQLAlchemy session.
        scenario_id: Scenario to query.
        sim_start_time: Start of the simulation window.
        sim_end_time: End of the simulation window.
        scaling: Annual scaling factor.

    Returns:
        Dict mapping ``VehicleType.id`` to ``(annual_vehicle_km,
        annual_revenue_km)``.
    """
    from eflips.model import Route  # local to avoid circular at module level

    # All trips within the simulation window, joined to rotation for
    # vehicle type and to route for distance.
    base_filter = (
        select(
            Rotation.vehicle_type_id,
            Trip.trip_type,
            func.sum(Route.distance).label("total_distance_m"),
        )
        .join(Rotation, Trip.rotation_id == Rotation.id)
        .join(Route, Trip.route_id == Route.id)
        .where(Rotation.scenario_id == scenario_id)
        .where(Trip.departure_time >= sim_start_time)
        .where(Trip.arrival_time <= sim_end_time)
        .group_by(Rotation.vehicle_type_id, Trip.trip_type)
    )

    rows = session.execute(base_filter).all()

    # Accumulate per vehicle type
    vkm: dict[int, float] = {}
    rkm: dict[int, float] = {}
    for vtype_id, trip_type, total_m in rows:
        km = (total_m / 1000.0) * scaling
        vkm[vtype_id] = vkm.get(vtype_id, 0.0) + km
        if trip_type == TripType.PASSENGER:
            rkm[vtype_id] = rkm.get(vtype_id, 0.0) + km

    # Merge
    all_ids = set(vkm) | set(rkm)
    return {vid: (vkm.get(vid, 0.0), rkm.get(vid, 0.0)) for vid in all_ids}


def _extract_n_ready(
    session: Session,
    scenario_id: int,
    sim_start_time: datetime,
    sim_end_time: datetime,
) -> dict[int, int]:
    """Count distinct vehicles used per vehicle type.

    Args:
        session: SQLAlchemy session.
        scenario_id: Scenario to query.
        sim_start_time: Start of the simulation window.
        sim_end_time: End of the simulation window.

    Returns:
        Dict mapping ``VehicleType.id`` to the count of distinct vehicles.
    """
    stmt = (
        select(
            Rotation.vehicle_type_id,
            func.count(sqlalchemy.distinct(Rotation.vehicle_id)).label("n"),
        )
        .join(Trip, Trip.rotation_id == Rotation.id)
        .where(Rotation.scenario_id == scenario_id)
        .where(Trip.departure_time >= sim_start_time)
        .where(Trip.arrival_time <= sim_end_time)
        .where(Rotation.vehicle_id.isnot(None))
        .group_by(Rotation.vehicle_type_id)
    )
    rows = session.execute(stmt).all()
    return {vtype_id: int(n) for vtype_id, n in rows}


def _extract_area_peaks(
    session: Session,
    scenario_id: int,
    sim_start_time: datetime,
    sim_end_time: datetime,
) -> dict[int, AreaSimData]:
    """Extract peak power and occupancy for BEV depot areas.

    Args:
        session: SQLAlchemy session.
        scenario_id: Scenario to query.
        sim_start_time: Start of the simulation window.
        sim_end_time: End of the simulation window.

    Returns:
        Dict mapping ``Area.id`` to ``AreaSimData``.
    """
    areas = (
        session.query(Area)
        .join(Depot, Area.depot_id == Depot.id)
        .join(VehicleType, Area.vehicle_type_id == VehicleType.id)
        .filter(Area.scenario_id == scenario_id)
        .filter(VehicleType.energy_source == EnergySource.BATTERY_ELECTRIC)
        .all()
    )

    result: dict[int, AreaSimData] = {}
    for area in areas:
        try:
            df = power_and_occupancy(
                area_id=area.id,
                session=session,
                sim_start_time=sim_start_time,
                sim_end_time=sim_end_time,
            )
        except ValueError:
            # No events for this area
            logger.warning("No events found for area %d, skipping.", area.id)
            continue

        peak_power = float(df["power"].max()) if not df.empty else 0.0
        peak_vehicles = int(df["occupancy_total"].max()) if not df.empty else 0
        result[area.id] = AreaSimData(
            area_id=area.id,
            peak_charging_power_kw=peak_power,
            peak_simultaneous_vehicles=peak_vehicles,
        )
    return result


def _extract_station_peaks(
    session: Session,
    scenario_id: int,
    sim_start_time: datetime,
    sim_end_time: datetime,
) -> dict[int, StationSimData]:
    """Extract peak power and occupancy for terminal stations.

    Only processes electrified stations that are *not* associated with a
    depot (``Station.depot is None``).

    Args:
        session: SQLAlchemy session.
        scenario_id: Scenario to query.
        sim_start_time: Start of the simulation window.
        sim_end_time: End of the simulation window.

    Returns:
        Dict mapping ``Station.id`` to ``StationSimData``.
    """
    from eflips.model import ChargeType

    stations = (
        session.query(Station)
        .outerjoin(Depot, Depot.station_id == Station.id)
        .filter(Station.scenario_id == scenario_id)
        .filter(Station.is_electrified.is_(True))
        .filter(Depot.id.is_(None))  # exclude depot-attached stations
        .all()
    )

    result: dict[int, StationSimData] = {}
    for station in stations:
        try:
            df = power_and_occupancy(
                area_id=[],
                station_id=station.id,
                session=session,
                sim_start_time=sim_start_time,
                sim_end_time=sim_end_time,
            )
        except ValueError:
            logger.warning("No events found for station %d, skipping.", station.id)
            continue

        peak_power = float(df["power"].max()) if not df.empty else 0.0
        peak_vehicles = int(df["occupancy_total"].max()) if not df.empty else 0
        result[station.id] = StationSimData(
            station_id=station.id,
            peak_charging_power_kw=peak_power,
            peak_simultaneous_vehicles=peak_vehicles,
        )
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_simulation_data(
    session: Session,
    scenario_id: int,
    sim_start_time: datetime,
    sim_end_time: datetime,
    eta_avail: float = 0.9,
) -> ScenarioSimData:
    """Extract all simulation outputs needed for the LCA calculation.

    Queries the eflips-model database for vehicle/revenue kilometres,
    fleet size, and peak charging infrastructure utilisation.  Energy
    and fuel consumption are **not** extracted here -- they are derived
    from ``lca_params`` in the calculation step.

    Args:
        session: SQLAlchemy session connected to an eflips-model database.
        scenario_id: ID of the scenario to analyse.
        sim_start_time: Start of the simulation time window.
        sim_end_time: End of the simulation time window.
        eta_avail: Technical availability factor (default ``0.9``).

    Returns:
        A ``ScenarioSimData`` containing all extracted values.

    Raises:
        ValueError: If the simulation window is non-positive.
    """
    scaling = _annual_scaling_factor(sim_start_time, sim_end_time)

    km_data = _extract_kilometres(
        session, scenario_id, sim_start_time, sim_end_time, scaling
    )
    n_ready_data = _extract_n_ready(session, scenario_id, sim_start_time, sim_end_time)

    vtype_sim: dict[int, VehicleTypeSimData] = {}
    for vtype_id in set(km_data) | set(n_ready_data):
        vkm, rkm = km_data.get(vtype_id, (0.0, 0.0))
        vtype_sim[vtype_id] = VehicleTypeSimData(
            vehicle_type_id=vtype_id,
            annual_vehicle_kilometers=vkm,
            annual_revenue_kilometers=rkm,
            n_ready=n_ready_data.get(vtype_id, 0),
        )

    area_data = _extract_area_peaks(session, scenario_id, sim_start_time, sim_end_time)
    station_data = _extract_station_peaks(
        session, scenario_id, sim_start_time, sim_end_time
    )

    return ScenarioSimData(
        vehicle_type_data=vtype_sim,
        area_data=area_data,
        station_data=station_data,
        eta_avail=eta_avail,
    )
