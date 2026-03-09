"""eflips-lca: Life Cycle Assessment for eFLIPS bus simulations.

Calculates per-revenue-km environmental impacts of electric (BEB) and
diesel (ICEB) bus fleets across their full life cycle, following
ISO 14040/14044.
"""

from eflips.lca.calculation import calculate_lca
from eflips.lca.dataclasses import (
    BatteryTypeLcaParams,
    ChargingPointTypeLcaParams,
    LcaResult,
    VehicleTypeLcaParams,
)
from eflips.lca.extraction import (
    AreaSimData,
    ScenarioSimData,
    StationSimData,
    VehicleTypeSimData,
    extract_simulation_data,
)
from eflips.lca.open_lca_data import (
    OpenLcaData,
    VehicleTypeOverrides,
    YearSeries,
    populate_lca_params_from_data,
    populate_lca_params_from_file,
)
from eflips.lca.util import DefaultImpactVector, ImpactVector

__all__ = [
    "ImpactVector",
    "DefaultImpactVector",
    "VehicleTypeLcaParams",
    "BatteryTypeLcaParams",
    "ChargingPointTypeLcaParams",
    "LcaResult",
    "ScenarioSimData",
    "VehicleTypeSimData",
    "AreaSimData",
    "StationSimData",
    "extract_simulation_data",
    "calculate_lca",
    "OpenLcaData",
    "YearSeries",
    "VehicleTypeOverrides",
    "populate_lca_params_from_data",
    "populate_lca_params_from_file",
]
