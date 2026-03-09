"""Tests for the intermediate openLCA data layer.

Covers:
1. ``YearSeries`` interpolation (exact, between, clamping, single point)
2. ``OpenLcaData`` JSON roundtrip
3. Population logic
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from eflips.lca.open_lca_data import (
    OpenLcaData,
    VehicleTypeOverrides,
    YearSeries,
    populate_lca_params_from_data,
    populate_lca_params_from_file,
)
from eflips.lca.util import DefaultImpactVector

# ===================================================================
# Helpers
# ===================================================================


def _iv(gwp: float) -> DefaultImpactVector:
    """Create a ``DefaultImpactVector`` with only gwp set."""
    return DefaultImpactVector(gwp=gwp)


def _make_open_lca_data() -> OpenLcaData:
    """Build a minimal ``OpenLcaData`` for testing."""
    return OpenLcaData(
        ecoinvent_version="3.9.1",
        lcia_method_set="EF 3.1",
        description="Test dataset",
        created_at="2025-01-01T00:00:00Z",
        chassis_per_kg=_iv(10.0),
        electric_motor_per_kg=_iv(5.0),
        diesel_motor_per_unit=_iv(8000.0),
        lfp_battery_per_kg=_iv(100.0),
        nmc_battery_per_kg=_iv(120.0),
        electricity_per_kwh=YearSeries(
            data={
                2025: _iv(0.4),
                2030: _iv(0.3),
                2035: _iv(0.2),
            }
        ),
        diesel_production_per_kg=_iv(0.5),
        diesel_combustion_per_kg=_iv(3.2),
        maintenance_iceb_per_year=_iv(1000.0),
        maintenance_beb_per_year=_iv(750.0),
        control_unit=_iv(500.0),
        power_unit_per_kg=_iv(30.0),
        user_unit_per_kg=_iv(25.0),
        concrete_per_m3=_iv(300.0),
        motor_power_to_weight_ratio_kw_per_kg=2.0,
        diesel_motor_mass_kg=1900.0,
        vehicle_lifetime_years=12.0,
        efficiency_mv_to_lv=0.99,
        efficiency_lv_ac_to_dc=0.95,
        battery_lifetime_years=8.0,
        beb_maintenance_reduction_factor=0.75,
        power_unit_mass_kg=700.0,
        power_unit_rated_power_kw=150.0,
        user_unit_mass_kg=20.0,
        foundation_volume_per_point_m3=3.96,
        infrastructure_lifetime_years=20.0,
    )


# ===================================================================
# YearSeries tests
# ===================================================================


class TestYearSeries:
    """Tests for ``YearSeries`` interpolation."""

    def test_exact_match(self) -> None:
        """Exact year returns the stored vector."""
        ys = YearSeries(data={2025: _iv(0.4), 2030: _iv(0.3)})
        result = ys.at_year(2025)
        assert result.gwp == pytest.approx(0.4)

    def test_interpolation_midpoint(self) -> None:
        """Midpoint between two years returns the average."""
        ys = YearSeries(data={2020: _iv(1.0), 2030: _iv(0.0)})
        result = ys.at_year(2025)
        assert result.gwp == pytest.approx(0.5)

    def test_interpolation_quarter(self) -> None:
        """Quarter point interpolation."""
        ys = YearSeries(data={2020: _iv(0.0), 2030: _iv(1.0)})
        result = ys.at_year(2022)  # t = 0.2
        assert result.gwp == pytest.approx(0.2)

    def test_clamp_below(self) -> None:
        """Year before range clamps to first and warns."""
        ys = YearSeries(data={2025: _iv(0.4), 2030: _iv(0.3)})
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = ys.at_year(2020)
            assert len(w) == 1
            assert "before the earliest" in str(w[0].message)
        assert result.gwp == pytest.approx(0.4)

    def test_clamp_above(self) -> None:
        """Year after range clamps to last and warns."""
        ys = YearSeries(data={2025: _iv(0.4), 2030: _iv(0.3)})
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = ys.at_year(2040)
            assert len(w) == 1
            assert "after the latest" in str(w[0].message)
        assert result.gwp == pytest.approx(0.3)

    def test_single_point_exact(self) -> None:
        """Single data point returns it for exact match."""
        ys = YearSeries(data={2025: _iv(0.4)})
        result = ys.at_year(2025)
        assert result.gwp == pytest.approx(0.4)

    def test_single_point_clamp(self) -> None:
        """Single data point clamps for any other year."""
        ys = YearSeries(data={2025: _iv(0.4)})
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = ys.at_year(2030)
            assert len(w) == 1
        assert result.gwp == pytest.approx(0.4)

    def test_empty_raises(self) -> None:
        """Empty series raises ValueError."""
        ys = YearSeries(data={})
        with pytest.raises(ValueError, match="empty"):
            ys.at_year(2025)

    def test_roundtrip(self) -> None:
        """to_dict/from_dict roundtrip preserves data."""
        ys = YearSeries(data={2025: _iv(0.4), 2030: _iv(0.3)})
        restored = YearSeries.from_dict(ys.to_dict())
        assert restored.at_year(2025).gwp == pytest.approx(0.4)
        assert restored.at_year(2030).gwp == pytest.approx(0.3)

    def test_all_categories_interpolated(self) -> None:
        """All 8 categories are interpolated, not just gwp."""
        iv_lo = DefaultImpactVector(
            gwp=1.0,
            pm=2.0,
            pocp=3.0,
            ap=4.0,
            ep_freshwater=5.0,
            ep_marine=6.0,
            fuel=7.0,
            water=8.0,
        )
        iv_hi = DefaultImpactVector(
            gwp=2.0,
            pm=4.0,
            pocp=6.0,
            ap=8.0,
            ep_freshwater=10.0,
            ep_marine=12.0,
            fuel=14.0,
            water=16.0,
        )
        ys = YearSeries(data={2020: iv_lo, 2030: iv_hi})
        result = ys.at_year(2025)
        assert result.gwp == pytest.approx(1.5)
        assert result.pm == pytest.approx(3.0)
        assert result.water == pytest.approx(12.0)


# ===================================================================
# OpenLcaData JSON roundtrip tests
# ===================================================================


class TestOpenLcaDataRoundtrip:
    """Tests for ``OpenLcaData`` serialization."""

    def test_dict_roundtrip(self) -> None:
        """to_dict/from_dict roundtrip preserves all fields."""
        original = _make_open_lca_data()
        restored = OpenLcaData.from_dict(original.to_dict())

        assert restored.ecoinvent_version == original.ecoinvent_version
        assert restored.lcia_method_set == original.lcia_method_set
        assert restored.description == original.description
        assert restored.created_at == original.created_at

        assert restored.chassis_per_kg.gwp == pytest.approx(original.chassis_per_kg.gwp)
        assert restored.electric_motor_per_kg.gwp == pytest.approx(
            original.electric_motor_per_kg.gwp
        )
        assert restored.diesel_motor_per_unit.gwp == pytest.approx(
            original.diesel_motor_per_unit.gwp
        )
        assert restored.lfp_battery_per_kg.gwp == pytest.approx(
            original.lfp_battery_per_kg.gwp
        )
        assert restored.nmc_battery_per_kg.gwp == pytest.approx(
            original.nmc_battery_per_kg.gwp
        )
        assert restored.electricity_per_kwh.at_year(2025).gwp == pytest.approx(0.4)
        assert restored.electricity_per_kwh.at_year(2030).gwp == pytest.approx(0.3)
        assert restored.diesel_production_per_kg.gwp == pytest.approx(
            original.diesel_production_per_kg.gwp
        )
        assert restored.diesel_combustion_per_kg.gwp == pytest.approx(
            original.diesel_combustion_per_kg.gwp
        )
        assert restored.maintenance_iceb_per_year.gwp == pytest.approx(
            original.maintenance_iceb_per_year.gwp
        )
        assert restored.maintenance_beb_per_year.gwp == pytest.approx(
            original.maintenance_beb_per_year.gwp
        )
        assert restored.control_unit.gwp == pytest.approx(original.control_unit.gwp)
        assert restored.power_unit_per_kg.gwp == pytest.approx(
            original.power_unit_per_kg.gwp
        )
        assert restored.user_unit_per_kg.gwp == pytest.approx(
            original.user_unit_per_kg.gwp
        )
        assert restored.concrete_per_m3.gwp == pytest.approx(
            original.concrete_per_m3.gwp
        )

        assert restored.motor_power_to_weight_ratio_kw_per_kg == pytest.approx(2.0)
        assert restored.diesel_motor_mass_kg == pytest.approx(1900.0)
        assert restored.vehicle_lifetime_years == pytest.approx(12.0)
        assert restored.efficiency_mv_to_lv == pytest.approx(0.99)
        assert restored.efficiency_lv_ac_to_dc == pytest.approx(0.95)
        assert restored.battery_lifetime_years == pytest.approx(8.0)
        assert restored.beb_maintenance_reduction_factor == pytest.approx(0.75)
        assert restored.power_unit_mass_kg == pytest.approx(700.0)
        assert restored.power_unit_rated_power_kw == pytest.approx(150.0)
        assert restored.user_unit_mass_kg == pytest.approx(20.0)
        assert restored.foundation_volume_per_point_m3 == pytest.approx(3.96)
        assert restored.infrastructure_lifetime_years == pytest.approx(20.0)

    def test_json_file_roundtrip(self, tmp_path: Path) -> None:
        """to_json/from_json roundtrip preserves all fields."""
        original = _make_open_lca_data()
        json_path = tmp_path / "test_data.json"
        original.to_json(json_path)
        restored = OpenLcaData.from_json(json_path)

        assert restored.ecoinvent_version == original.ecoinvent_version
        assert restored.chassis_per_kg.gwp == pytest.approx(original.chassis_per_kg.gwp)
        assert restored.electricity_per_kwh.at_year(2030).gwp == pytest.approx(0.3)
        assert restored.motor_power_to_weight_ratio_kw_per_kg == pytest.approx(2.0)
        assert restored.infrastructure_lifetime_years == pytest.approx(20.0)

    def test_scalar_defaults_when_missing(self) -> None:
        """Scalar fields fall back to defaults when absent from dict."""
        original = _make_open_lca_data()
        d = original.to_dict()
        # Remove optional scalar fields
        del d["diesel_motor_mass_kg"]
        del d["vehicle_lifetime_years"]
        del d["efficiency_mv_to_lv"]
        restored = OpenLcaData.from_dict(d)
        assert restored.diesel_motor_mass_kg == pytest.approx(1900.0)
        assert restored.vehicle_lifetime_years == pytest.approx(12.0)
        assert restored.efficiency_mv_to_lv == pytest.approx(0.99)


# ===================================================================
# Population logic tests
# ===================================================================


class TestPopulationLogic:
    """Tests for ``populate_lca_params_from_data`` and ``populate_lca_params_from_file``."""

    def test_populate_from_data(self, db_session: pytest.fixture) -> None:  # type: ignore[type-arg]
        """Populating from OpenLcaData writes expected lca_params."""
        from eflips.model import VehicleType

        data = _make_open_lca_data()
        overrides = {
            12: VehicleTypeOverrides(
                motor_rated_power_kw=200.0,
                average_consumption_kwh_per_km=1.2,
            ),
            13: VehicleTypeOverrides(
                motor_rated_power_kw=300.0,
                average_consumption_kwh_per_km=1.8,
            ),
            14: VehicleTypeOverrides(
                motor_rated_power_kw=250.0,
                average_consumption_kwh_per_km=1.5,
            ),
        }

        populate_lca_params_from_data(
            session=db_session,
            scenario_id=1,
            open_lca_data=data,
            year=2025,
            vehicle_type_overrides=overrides,
        )

        vtype = db_session.query(VehicleType).filter_by(id=12).one()
        assert vtype.lca_params is not None
        params = vtype.lca_params
        # Chassis EF should match openLCA data
        assert params["chassis_emission_factors_per_kg"]["gwp"] == pytest.approx(10.0)
        # Motor EF should match
        assert params["motor_emission_factors_per_kg"]["gwp"] == pytest.approx(5.0)
        # Electricity should be from year 2025
        assert params["electricity_emission_factors_per_kwh"]["gwp"] == pytest.approx(
            0.4
        )
        # Motor mass should be power / ratio = 200 / 2.0 = 100
        assert params["motor_mass_kg"] == pytest.approx(100.0)
        # Consumption override applied
        assert params["average_consumption_kwh_per_km"] == pytest.approx(1.2)

    def test_populate_from_file(
        self, db_session: pytest.fixture, tmp_path: Path  # type: ignore[type-arg]
    ) -> None:
        """Populating from a JSON file works end-to-end."""
        from eflips.model import BatteryType

        data = _make_open_lca_data()
        json_path = tmp_path / "openlca_data_test.json"
        data.to_json(json_path)

        overrides = {
            12: VehicleTypeOverrides(
                motor_rated_power_kw=200.0,
                average_consumption_kwh_per_km=1.2,
            ),
            13: VehicleTypeOverrides(
                motor_rated_power_kw=300.0,
                average_consumption_kwh_per_km=1.8,
            ),
            14: VehicleTypeOverrides(
                motor_rated_power_kw=250.0,
                average_consumption_kwh_per_km=1.5,
            ),
        }

        populate_lca_params_from_file(
            session=db_session,
            scenario_id=1,
            json_path=json_path,
            year=2030,
            vehicle_type_overrides=overrides,
        )

        # Verify battery type got LFP params
        bt = db_session.query(BatteryType).filter_by(scenario_id=1).first()
        assert bt is not None
        assert bt.lca_params is not None
        assert bt.lca_params["emission_factors_per_kg"]["gwp"] == pytest.approx(100.0)
        assert bt.lca_params["battery_lifetime_years"] == pytest.approx(8.0)

    def test_interpolated_electricity_year(self, db_session: pytest.fixture) -> None:  # type: ignore[type-arg]
        """Populating with an interpolated year uses correct electricity EF."""
        from eflips.model import VehicleType

        data = _make_open_lca_data()
        overrides = {
            12: VehicleTypeOverrides(
                motor_rated_power_kw=200.0,
                average_consumption_kwh_per_km=1.2,
            ),
        }

        populate_lca_params_from_data(
            session=db_session,
            scenario_id=1,
            open_lca_data=data,
            year=2027,  # Between 2025 (0.4) and 2030 (0.3) → t=0.4 → 0.36
            vehicle_type_overrides=overrides,
        )

        vtype = db_session.query(VehicleType).filter_by(id=12).one()
        assert vtype.lca_params is not None
        expected_gwp = 0.4 * (1 - 0.4) + 0.3 * 0.4  # = 0.36
        assert vtype.lca_params["electricity_emission_factors_per_kwh"][
            "gwp"
        ] == pytest.approx(expected_gwp)
