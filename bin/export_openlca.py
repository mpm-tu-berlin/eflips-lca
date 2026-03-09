#!/usr/bin/env python3
"""Export openLCA data to a JSON file for eflips-lca.

Standalone CLI script that connects to an openLCA IPC server, queries
all required ecoinvent processes, collects scalar parameters, and
writes an ``OpenLcaData`` JSON file.

Usage::

    python bin/export_openlca.py --output data/openlca_data_v3.9.1.json

Prerequisites::

    pip install olca-ipc
    # An openLCA IPC server must be running with an ecoinvent database.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# LCIA method and ecoinvent process mappings
# ---------------------------------------------------------------------------

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


def _query_impact_vector(
    client: Any,
    process_name: str,
    amount: float = 1.0,
) -> dict[str, float]:
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
        return impacts

    Args:
        client: An ``olca_ipc.Client`` connected to an openLCA IPC server.
        process_name: The name of the ecoinvent process to query.
        amount: The reference flow amount (default ``1.0``).

    Returns:
        A dict mapping field names to impact values.

    Raises:
        NotImplementedError: Always -- this is a placeholder.
    """
    raise NotImplementedError(
        "openLCA integration not yet implemented. "
        "See docstring and ECOINVENT_PROCESS_MAPPING for guidance."
    )


def export_openlca_data(
    client: Any,
    output_path: str,
    ecoinvent_version: str = "3.9.1",
    lcia_method_set: str = "EF 3.1",
    description: str = "",
) -> None:
    """Query openLCA and write an OpenLcaData JSON file.

    .. note::
        This is a **placeholder** demonstrating the intended workflow.
        Each ``_query_impact_vector`` call must be implemented for the
        actual openLCA IPC API.

    Args:
        client: An ``olca_ipc.Client`` connected to an openLCA IPC server.
        output_path: Path for the output JSON file.
        ecoinvent_version: Version of the ecoinvent database.
        lcia_method_set: Name of the LCIA method set.
        description: Free-text description.

    Raises:
        NotImplementedError: Always -- placeholder queries are not
            implemented.
    """
    # This is the intended workflow once openLCA IPC is available:
    #
    # from eflips.lca.open_lca_data import OpenLcaData, YearSeries
    # from eflips.lca.util import DefaultImpactVector
    #
    # chassis_iv = DefaultImpactVector(**_query_impact_vector(
    #     client, ECOINVENT_PROCESS_MAPPING["chassis_bus_production"]
    # ))
    # ... (query all processes) ...
    #
    # data = OpenLcaData(
    #     ecoinvent_version=ecoinvent_version,
    #     lcia_method_set=lcia_method_set,
    #     description=description,
    #     created_at=datetime.now(timezone.utc).isoformat(),
    #     chassis_per_kg=chassis_iv,
    #     ... (all fields) ...
    # )
    # data.to_json(output_path)
    raise NotImplementedError(
        "Full openLCA export workflow not yet implemented. "
        "See docstring for step-by-step guidance."
    )


def main() -> None:
    """CLI entry point for exporting openLCA data."""
    parser = argparse.ArgumentParser(
        description="Export openLCA data to JSON for eflips-lca"
    )
    parser.add_argument(
        "--output",
        "-o",
        required=True,
        help="Output JSON file path",
    )
    parser.add_argument(
        "--ecoinvent-version",
        default="3.9.1",
        help="Ecoinvent database version (default: 3.9.1)",
    )
    parser.add_argument(
        "--lcia-method-set",
        default="EF 3.1",
        help="LCIA method set name (default: EF 3.1)",
    )
    parser.add_argument(
        "--description",
        default="",
        help="Free-text description for this dataset",
    )
    args = parser.parse_args()

    # TODO: Initialize olca_ipc.Client here
    # import olca_ipc as ipc
    # client = ipc.Client()

    print(
        "ERROR: openLCA IPC client not yet implemented. "
        "This script is a placeholder showing the intended workflow.",
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
