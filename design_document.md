# eflips-lca Design Document

The eflips-lca package calculates the environmental impact of electric (BEB) and conventional diesel (ICEB) bus fleets across their full life cycle. It loads environmental parameters from `lca_params` JSONB columns on eflips-model database entities (`VehicleType`, `BatteryType`, etc.) and combines them with simulation outputs to produce per-Nutzwagenkilometer impact assessments.

The methodology follows **ISO 14040/14044** and applies a **Cradle-to-Grave** system boundary. The functional unit is the **Nutzwagenkilometer** (Nwkm) — the distance driven by a bus while in revenue service, independent of passenger load — providing a robust basis for comparing propulsion technologies.

### Data Source Classification

Parameters are classified by origin (matching the SVG diagrams):

| Color | Source | Examples |
|-------|--------|----------|
| Blue | **eFLIPS** | Simulation outputs: energy consumption, vehicle-km, fleet size, charging layout |
| Red | **openLCA / ecoinvent** | Environmental impact factors from LCA databases |
| Green | **Literature** | Physical constants, efficiencies, lifetimes, energy densities |

---

## Part 1: LCA Methodology and Parameters

### 1.1 Environmental Impact Categories

All calculations produce results as an **ImpactVector** — a vector of environmental impact categories. The vector is designed to be **flexible and statically typed**: categories are defined as named `float` fields on a subclass, not in a runtime dictionary. This means categories are established at code-write time, type-checked by static analyzers, and autocompleted by IDEs.

The `ImpactVector` base class uses `dataclasses.fields()` — the standard-library introspection mechanism — to implement arithmetic generically over whatever fields a subclass defines. The arithmetic methods never need to be changed when categories are added or removed:

```python
from dataclasses import dataclass, fields as dc_fields

@dataclass
class ImpactVector:
    """Base class for environmental impact vectors.

    To define a category set, subclass this and add float fields with default 0.0:

        @dataclass
        class MyImpactVector(ImpactVector):
            gwp: float = 0.0   # kg CO2 eq
            pm: float = 0.0    # kg PM2.5 eq

    Arithmetic is implemented generically via dataclasses.fields() and works
    for any subclass without modification.
    """

    def _check_compatible(self, other: "ImpactVector") -> None:
        if type(self) is not type(other):
            raise TypeError(
                f"Cannot combine {type(self).__name__} and {type(other).__name__}"
            )

    def __add__(self, other: "ImpactVector") -> "ImpactVector":
        self._check_compatible(other)
        return type(self)(**{f.name: getattr(self, f.name) + getattr(other, f.name)
                             for f in dc_fields(self)})

    def __sub__(self, other: "ImpactVector") -> "ImpactVector":
        self._check_compatible(other)
        return type(self)(**{f.name: getattr(self, f.name) - getattr(other, f.name)
                             for f in dc_fields(self)})

    def __mul__(self, scalar: float) -> "ImpactVector":
        return type(self)(**{f.name: getattr(self, f.name) * scalar
                             for f in dc_fields(self)})

    def __rmul__(self, scalar: float) -> "ImpactVector":
        return self.__mul__(scalar)

    def __truediv__(self, scalar: float) -> "ImpactVector":
        return type(self)(**{f.name: getattr(self, f.name) / scalar
                             for f in dc_fields(self)})

    def __neg__(self) -> "ImpactVector":
        return type(self)(**{f.name: -getattr(self, f.name) for f in dc_fields(self)})


@dataclass
class DefaultImpactVector(ImpactVector):
    """The default 8-category impact vector used by this package.

    Subclass to add categories or replace with a different set.
    """
    gwp: float = 0.0           # kg CO2 eq   — Global warming potential (100a)
    pm: float = 0.0            # kg PM2.5 eq  — Particulate matter formation
    pocp: float = 0.0          # kg NOx eq    — Photochemical ozone creation
    ap: float = 0.0            # kg SO2 eq    — Acidification potential
    ep_freshwater: float = 0.0 # kg P eq      — Freshwater eutrophication
    ep_marine: float = 0.0     # kg N eq      — Marine eutrophication
    fuel: float = 0.0          # kg Oil eq    — Fossil resource depletion
    water: float = 0.0         # m³           — Water consumption
```

The default 8 categories:

| # | Category | Field | Unit | Description |
|---|----------|-------|------|-------------|
| 1 | Treibhauspotenzial | `gwp` | kg CO2 eq | Global warming potential (100a) |
| 2 | Feinstaub | `pm` | kg PM2.5 eq | Particulate matter formation |
| 3 | Photochem. Ozon | `pocp` | kg NOx eq | Photochemical ozone creation |
| 4 | Versauerung | `ap` | kg SO2 eq | Acidification potential |
| 5 | Eutrophierung (Süßwasser) | `ep_freshwater` | kg P eq | Freshwater eutrophication |
| 6 | Eutrophierung (Meer) | `ep_marine` | kg N eq | Marine eutrophication |
| 7 | Fossile Ressourcen | `fuel` | kg Oil eq | Fossil resource depletion |
| 8 | Wasserverbrauch | `water` | m³ | Water consumption |

Throughout this document, $\mathbf{e}$ denotes an ImpactVector. Subscripts identify *what* it measures; the mathematical operations apply element-wise across all fields.

---

### 1.2 Grand Scheme

The total life-cycle emissions per Nutzwagenkilometer combine two lifecycle phases plus charging infrastructure:

$$
\mathbf{e}_{\text{total, per Nwkm}} = \mathbf{e}_{\text{production, per Nwkm}} + \mathbf{e}_{\text{use, per Nwkm}} + \mathbf{e}_{\text{infrastructure, per Nwkm}}
$$

| Contributor | What it covers | Applies to |
|-------------|---------------|------------|
| **Production + EoL** *(lifecycle phase)* | Manufacturing and disposal of vehicle components (chassis, motor, battery) | BEB and ICEB |
| **Use Phase** *(lifecycle phase)* | Energy consumption (electricity or diesel) and maintenance | BEB and ICEB |
| **Charging Infrastructure** | Manufacturing and disposal of charging equipment | BEB only ($= \mathbf{0}$ for ICEB) |

Each contributor follows the same general flow:

```
Per-component emissions
  → Sum to per-vehicle (or per-station) emissions
    → Amortize over lifetime → annual emissions
      → Normalize by Nutzwagenkilometer → per-Nwkm emissions
```

---

### 1.3 Recurring Calculation Patterns

Five patterns appear repeatedly. The code should implement these as reusable building blocks:

#### Pattern A: Mass-Based Scaling

Emissions scale linearly with mass. Used for chassis, electric motor, battery, power unit, user unit.

$$
E = m \times \mathbf{e}_{\text{per kg}}
$$

#### Pattern B: Fixed Per-Unit Emissions

Emissions for one complete unit. Used for diesel motor, control unit.

$$
E = \mathbf{e}_{\text{per unit}}
$$

#### Pattern C: Lifetime Amortization

Spread total emissions over operating years.

$$
E_{\text{annual}} = \frac{E_{\text{total}}}{L}
$$

#### Pattern D: Efficiency Chain

Scale energy consumption upstream through a chain of conversion efficiencies.

$$
E_{\text{upstream}} = \frac{E_{\text{downstream}}}{\prod_i \eta_i}
$$

#### Pattern E: Normalization to Nutzwagenkilometer

Convert annual fleet emissions to the functional unit.

$$
\mathbf{e}_{\text{per Nwkm}} = \frac{E_{\text{annual}} \times n_{\text{vehicles}}}{\text{Nwkm}_{\text{annual}}}
$$

---

### 1.4 Production and End-of-Life Phase

This phase captures all emissions from raw material extraction, manufacturing, and disposal/recycling of bus components. See the **Production SVG** for the visual flow.

#### 1.4.1 Vehicle Decomposition

A bus is decomposed into three components, each with independent emission factors and potentially different lifetimes:

| Component | Description | Scaling Law |
|-----------|-------------|-------------|
| **Chassis** ("Glider") | Everything that is neither motor nor energy storage | Pattern A: per kg |
| **Motor** | Electric motor or diesel engine | Electric: Pattern A; Diesel: Pattern B |
| **Battery** | Traction battery (BEB only; absent for ICEB) | Pattern A: per kg |

#### 1.4.2 Chassis

The chassis emission factors are derived from an 11-tonne diesel bus process in ecoinvent, with the diesel engine mass subtracted. The resulting **per-kg** factors are then linearly scaled to the actual chassis mass of any bus.

The chassis mass is derived by subtracting the motor and battery masses from the vehicle's curb weight (`VehicleType.empty_mass` in eflips-model):

$$
m_{\text{chassis}} = m_{\text{curb}} - m_{\text{motor}} - m_{\text{battery}}
$$

$$
E_{\text{chassis}} = m_{\text{chassis}} \times \mathbf{e}_{\text{chassis, per kg}}
$$

**Parameters** (stored in `VehicleType.lca_params`):

| Parameter | Type | Source | Description |
|-----------|------|--------|-------------|
| `chassis_emission_factors_per_kg` | ImpactVector | openLCA | Prod+EoL emissions per kg of chassis |

**From eflips-model**: `VehicleType.empty_mass` provides $m_{\text{curb}}$ in kg.

#### 1.4.3 Motor — Electric

Electric motor emissions scale linearly with mass (Pattern A). The mass is derived from the rated power and a literature-based power-to-weight ratio:

$$
m_{\text{motor}} = \frac{P_{\text{rated}}}{\rho_{\text{power-to-weight}}}
$$

$$
E_{\text{motor, electric}} = m_{\text{motor}} \times \mathbf{e}_{\text{motor, per kg}}
$$

**Parameters** (stored in `VehicleType.lca_params`):

| Parameter | Type | Source | Description |
|-----------|------|--------|-------------|
| `motor_rated_power_kw` | float | eFLIPS / datasheet | Rated motor power in kW |
| `motor_emission_factors_per_kg` | ImpactVector | openLCA | Prod+EoL emissions per kg of electric motor |
| `motor_power_to_weight_ratio` | float | Literature | kW/kg, to derive motor mass from power |

The ecoinvent process `market for electric motor, vehicle` provides per-kg factors, assuming a vehicle-scale electric motor can be linearly scaled to bus size.

#### 1.4.4 Motor — Diesel

Diesel motors use a fixed-weight assumption (Pattern B). The 1,900 kg reference motor has an approximate material composition of 2% aluminum, 9% polyethylene, and 89% steel. A custom openLCA process assembles these material production processes by mass fraction.

$$
E_{\text{motor, diesel}} = \mathbf{e}_{\text{diesel motor, per unit}}
$$

The diesel motor mass ($m_{\text{motor}} = 1{,}900\;\text{kg}$) is used to derive $m_{\text{chassis}}$ but emissions are not scaled — they are per complete motor.

**Parameters** (stored in `VehicleType.lca_params`):

| Parameter | Type | Source | Description |
|-----------|------|--------|-------------|
| `motor_emission_factors_per_unit` | ImpactVector | openLCA | Prod+EoL emissions for one diesel motor |
| `motor_mass_kg` | float | Literature | Mass of the diesel motor (default: 1,900 kg) |

#### 1.4.5 Battery

Battery emissions depend on cell chemistry (LFP or NMC622) and are given per kg (Pattern A). The battery mass is derived from the nominal capacity and the pack-level specific mass, both of which already exist on `BatteryType` in eflips-model:

$$
m_{\text{battery}} = C_{\text{nominal}} \times \sigma_{\text{specific}}
$$

$$
E_{\text{battery}} = m_{\text{battery}} \times \mathbf{e}_{\text{battery, per kg}}
$$

where $C_{\text{nominal}}$ is `VehicleType.battery_capacity` in kWh and $\sigma_{\text{specific}}$ is `BatteryType.specific_mass` in kg/kWh. The `BatteryType.chemistry` string identifies the cell chemistry (e.g. `"LFP"` or `"NMC622"`).

For ICEB vehicles (no battery), $E_{\text{battery}} = \mathbf{0}$ and $m_{\text{battery}} = 0$.

**Parameters** (stored in `BatteryType.lca_params`):

| Parameter | Type | Source | Description |
|-----------|------|--------|-------------|
| `emission_factors_per_kg` | ImpactVector | openLCA | Prod+EoL emissions per kg of battery pack |
| `battery_lifetime_years` | float | Literature | Battery lifetime for LCA amortization (default: 8) |

**From eflips-model**:
- `VehicleType.battery_capacity` → $C_{\text{nominal}}$ (kWh)
- `BatteryType.specific_mass` → $\sigma_{\text{specific}}$ (kg/kWh)
- `BatteryType.chemistry` → string identifying chemistry for selecting correct emission factors

**Consistency check**: If `BatteryType.tco_parameters["useful_life"]` is set and differs from `battery_lifetime_years`, emit a `warnings.warn()` to alert the user to the mismatch between TCO and LCA assumptions.

#### 1.4.6 Total Vehicle Production Emissions and Lifetime Amortization

Total vehicle production + EoL emissions:

$$
E_{\text{vehicle}} = E_{\text{chassis}} + E_{\text{motor}} + E_{\text{battery}}
$$

These are amortized to one operating year (Pattern C). Motor and chassis share a common vehicle lifetime ($L_{\text{vehicle}}$); the battery has a separate, typically shorter lifetime ($L_{\text{battery}}$):

**BEB (Battery Electric Bus):**

$$
E_{\text{prod, annual}} = \frac{E_{\text{battery}}}{L_{\text{battery}}} + \frac{E_{\text{motor}} + E_{\text{chassis}}}{L_{\text{vehicle}}}
$$

The battery term $E_{\text{battery}} / L_{\text{battery}}$ represents the annualized cost of always having a battery. If the battery lifetime (e.g., 8 years) is shorter than the vehicle lifetime (e.g., 12 years), replacement is implicitly covered: each year "costs" $1/L_{\text{battery}}$ of a battery's production emissions.

**ICEB (Internal Combustion Engine Bus):**

$$
E_{\text{prod, annual}} = \frac{E_{\text{motor}} + E_{\text{chassis}}}{L_{\text{vehicle}}}
$$

**Parameters** (stored in `VehicleType.lca_params`):

| Parameter | Type | Source | Description |
|-----------|------|--------|-------------|
| `vehicle_lifetime_years` | float | Literature | Motor + chassis lifetime (default: 12) |

The battery lifetime is on `BatteryType.lca_params.battery_lifetime_years` (see §1.4.5).

#### 1.4.7 Fleet Aggregation to Nutzwagenkilometer

To convert per-vehicle annual emissions to per-Nutzwagenkilometer, we must account for the total fleet size including vehicles in maintenance.

From eFLIPS, we obtain $n_{\text{ready}}$: the number of operationally ready vehicles needed for service (per vehicle type). The **total fleet** (including maintenance spares) is:

$$
n_{\text{total}} = \frac{n_{\text{ready}}}{\eta_{\text{avail}}}
$$

where $\eta_{\text{avail}}$ is the technical availability (e.g., 0.9 meaning 90% of vehicles are available at any time). This reflects that we manufacture more vehicles than are simultaneously in service.

**Per vehicle type:**

$$
\mathbf{e}_{\text{prod, per Nwkm}}^{(t)} = \frac{E_{\text{prod, annual}}^{(t)} \times n_{\text{total}}^{(t)}}{\text{Nwkm}^{(t)}}
$$

**Fleet-wide** (summed across all vehicle types $t$):

$$
\mathbf{e}_{\text{prod, per Nwkm}}^{\text{fleet}} = \frac{\sum_t E_{\text{prod, annual}}^{(t)} \times n_{\text{total}}^{(t)}}{\sum_t \text{Nwkm}^{(t)}}
$$

**Parameters** (from eFLIPS simulation):

| Parameter | Source | Description |
|-----------|--------|-------------|
| $n_{\text{ready}}^{(t)}$ | eFLIPS | Operationally ready vehicles per type |
| $\text{Nwkm}^{(t)}$ | eFLIPS | Annual Nutzwagenkilometer per type |
| $\eta_{\text{avail}}$ | Literature | Technical availability factor (default: ~0.9) |

---

### 1.5 Use Phase

The use phase captures emissions from vehicle operation (energy consumption) and maintenance. See the **Use Phase SVG** for the visual flow.

#### 1.5.1 Energy Consumption — Electricity (BEB)

The electricity drawn from the battery (a simulation output from eFLIPS) must be scaled up through an efficiency chain (Pattern D) to determine how much grid electricity is consumed:

$$
E_{\text{grid}} = \frac{E_{\text{battery}}}{\eta_{\text{MV} \to \text{LV}} \times \eta_{\text{AC} \to \text{DC}} \times \eta_{\text{battery}}}
$$

where:
- $\eta_{\text{MV} \to \text{LV}}$: medium voltage to low voltage transformer efficiency (default: 0.99)
- $\eta_{\text{AC} \to \text{DC}}$: AC to DC rectification efficiency (default: 0.95)
- $\eta_{\text{battery}}$: battery charging efficiency (available as `VehicleType.charging_efficiency` in eflips-model, default: 0.95)

The environmental impact is then (Pattern A applied to energy):

$$
\mathbf{e}_{\text{electricity, annual}} = E_{\text{grid}} \times \mathbf{e}_{\text{per kWh}}
$$

The emission factors per kWh are **year-specific** to account for changes in the electricity generation mix over time.

**Parameters** (stored in `VehicleType.lca_params`):

| Parameter | Type | Source | Description |
|-----------|------|--------|-------------|
| `efficiency_mv_to_lv` | float | Literature | MV to LV transformer efficiency (default: 0.99) |
| `efficiency_lv_ac_to_dc` | float | Literature | AC/DC rectification efficiency (default: 0.95) |
| `electricity_emission_factors_per_kwh` | ImpactVector | openLCA | Emissions per kWh of grid electricity |

**From eflips-model**: `VehicleType.charging_efficiency` provides $\eta_{\text{battery}}$.

**From eFLIPS simulation**: Annual energy drawn from the battery in kWh ($E_{\text{battery}}$), as a fleet aggregate for all ready vehicles of that type.

#### 1.5.2 Energy Consumption — Diesel (ICEB)

Total diesel emissions combine production (well-to-tank) and combustion (tank-to-wheel):

$$
\mathbf{e}_{\text{diesel, per kg}} = \mathbf{e}_{\text{production}} + \mathbf{e}_{\text{combustion}}
$$

$$
\mathbf{e}_{\text{diesel, annual}} = m_{\text{diesel, annual}} \times \mathbf{e}_{\text{diesel, per kg}}
$$

The annual diesel mass $m_{\text{diesel, annual}}$ comes from the eFLIPS simulation as a fleet aggregate.

**Parameters** (stored in `VehicleType.lca_params`):

| Parameter | Type | Source | Description |
|-----------|------|--------|-------------|
| `diesel_emission_factors_production_per_kg` | ImpactVector | openLCA | Well-to-tank emissions per kg diesel |
| `diesel_emission_factors_combustion_per_kg` | ImpactVector | openLCA | Tank-to-wheel emissions per kg diesel |

> **Note**: The combustion emission factors in ecoinvent use the process `diesel, burned in agricultural machinery` with a reference unit of 1 MJ, scaled by ~45 to obtain per-kg values (1 kg diesel $\approx$ 45 MJ lower heating value). **This process choice and scaling should be verified against the openLCA database** — a bus-specific combustion process may be more appropriate if available.

#### 1.5.3 Maintenance

Maintenance emissions account for replacement parts (oil, filters, brakes, tires, coolant) over the operating life. The ecoinvent process `market for maintenance, bus` gives emissions for **one bus per year** for an ICEB. The BEB value is obtained separately from literature-adjusted ecoinvent data (typically ~75% lower than ICEB due to no oil changes, regenerative braking, fewer moving parts, etc.).

Each vehicle type has its own maintenance emission factor keyed by `EnergySource`:

$$
\mathbf{e}_{\text{maint, annual per vehicle}} = \text{maintenance\_per\_year}[\text{energy\_source}]
$$

Because maintenance is **per vehicle** (not a fleet aggregate from simulation), it must be scaled to the full fleet including spares:

$$
\mathbf{e}_{\text{maint, annual fleet}} = \mathbf{e}_{\text{maint, annual per vehicle}} \times n_{\text{total}}
$$

**Parameters** (stored in `VehicleType.lca_params`):

| Parameter | Type | Source | Description |
|-----------|------|--------|-------------|
| `maintenance_per_year` | `dict[EnergySource, ImpactVector]` | openLCA / Literature | Annual maintenance emissions per vehicle, keyed by energy source |

The dict must contain an entry for the vehicle type's `energy_source`. Typical keys: `EnergySource.BATTERY_ELECTRIC`, `EnergySource.DIESEL`.

#### 1.5.4 Use Phase: Normalization to Nutzwagenkilometer

The energy emission `e_energy_annual` comes from eFLIPS as a **fleet aggregate** for all ready vehicles of a type. Maintenance `e_maint_annual_per_vehicle` is **per vehicle** and must be multiplied by `n_total`:

$$
\mathbf{e}_{\text{use, per Nwkm}} = \frac{\mathbf{e}_{\text{energy, annual}} + \mathbf{e}_{\text{maint, annual per vehicle}} \times n_{\text{total}}}{\text{Nwkm}_{\text{annual}}}
$$

**From eFLIPS simulation**: Annual Nutzwagenkilometer per vehicle type.

---

### 1.6 Charging Infrastructure

Charging infrastructure emissions apply only to BEB scenarios ($\mathbf{e}_{\text{infra}} = \mathbf{0}$ for ICEB). See the **Charging Infrastructure SVG** for the visual flow. The infrastructure is modeled using a component-based approach following the Tritium system architecture.

#### 1.6.1 Infrastructure Components

The charging system consists of three components with different scaling behaviors:

| Component | Description | Scaling | Source |
|-----------|-------------|---------|--------|
| **Control Unit** | Central controller | 1 per `Area`, 1 per terminal `Station` — Pattern B | openLCA (custom process) |
| **Power Unit** | Power electronics cabinet | Scales with total peak power (kW) — Pattern A | openLCA (custom process) |
| **User Unit** | Charging connector/plug or pantograph | Scales with number of charging points — Pattern A | openLCA (custom process) |

**One control unit per location**: each depot charging `Area` gets exactly one control unit; each electrified terminal `Station` (not depot-connected, see §1.6.3) gets exactly one control unit.

Additionally, for **terminal (Endhaltestelle) chargers**, a concrete foundation is required per charging point.

The per-kW emission factor for the power unit is derived from the per-kg emissions and the unit's specifications:

$$
\mathbf{e}_{\text{power, per kW}} = \frac{\mathbf{e}_{\text{power, per kg}} \times m_{\text{power unit}}}{P_{\text{rated, per unit}}}
$$

The per-plug emission factor for the user unit:

$$
\mathbf{e}_{\text{user, per plug}} = \mathbf{e}_{\text{user, per kg}} \times m_{\text{user unit}}
$$

#### 1.6.2 Depot Charging (Ladepark im Depot)

For each depot charging `Area`:

**BEV filter**: Only include the `Area` if `Area.vehicle_type.energy_source == EnergySource.BATTERY_ELECTRIC`. Areas serving diesel vehicle types are ignored.

$$
E_{\text{depot}} = P_{\text{peak}} \times \mathbf{e}_{\text{power, per kW}} + n_{\text{plugs}} \times \mathbf{e}_{\text{user, per plug}} + \mathbf{e}_{\text{control unit}}
$$

Amortized per year (Pattern C):

$$
\mathbf{e}_{\text{depot, annual}} = \frac{E_{\text{depot}}}{L_{\text{infra}}}
$$

where $P_{\text{peak}}$ is the total peak charging power (from eFLIPS), $n_{\text{plugs}}$ is `Area.capacity`, and $L_{\text{infra}}$ is the infrastructure lifetime from `ChargingPointType.lca_params`.

**Oversizing check**: Compare the peak simultaneous vehicle count (from eFLIPS simulation) against `Area.capacity`:
- If `peak_vehicles < 0.80 × Area.capacity`: `warnings.warn(...)` — significantly oversized; the LCA infrastructure count is inflated.
- If `0.80 × Area.capacity $\leq$ peak_vehicles < Area.capacity`: `logger.warning(...)` — mildly undersaturated.

> **Implementation note**: Deriving peak simultaneous vehicle count from simulation Events is non-trivial; the exact method is TBD and will require additional analysis of eFLIPS simulation output.

#### 1.6.3 Terminal Charging (Elektrifizierte Endhaltestelle)

**Depot-station exclusion**: A `Station` with an associated `Depot` (`Station.depot is not None`) must **not** be processed as a terminal charger. Its charging infrastructure is already accounted for through the depot's `Area` objects (§1.6.2). Only process electrified `Station` objects with `charge_type == oppb` **and** `Station.depot is None`.

For each qualifying terminal stop:

$$
E_{\text{terminal}} = P_{\text{peak}} \times \mathbf{e}_{\text{power, per kW}} + n_{\text{plugs}} \times \mathbf{e}_{\text{user, per plug}} + n_{\text{plugs}} \times V_{\text{foundation}} \times \mathbf{e}_{\text{concrete, per m³}} + \mathbf{e}_{\text{control unit}}
$$

Amortized identically to depot charging (Pattern C).

Data from eflips-model: `Station.amount_charging_places` → $n_{\text{plugs}}$, `Station.power_total` → $P_{\text{peak}}$.

**Oversizing check**: Same as §1.6.2, using `Station.amount_charging_places` as capacity.

#### 1.6.4 Aggregation to Nutzwagenkilometer

Total annual infrastructure emissions across all depots and terminals divided by total fleet Nutzwagenkilometer:

$$
\mathbf{e}_{\text{infra, per Nwkm}} = \frac{\sum_d \mathbf{e}_{\text{depot},d,\text{annual}} + \sum_s \mathbf{e}_{\text{terminal},s,\text{annual}}}{\text{Nwkm}_{\text{fleet}}}
$$

---

### 1.7 Putting It All Together

The complete formula for total life-cycle emissions per Nutzwagenkilometer:

$$
\mathbf{e}_{\text{total}} =
\underbrace{\frac{\sum_t \left(\frac{E_{\text{battery}}^{(t)}}{L_{\text{bat}}} + \frac{E_{\text{motor}}^{(t)} + E_{\text{chassis}}^{(t)}}{L_{\text{veh}}}\right) \times n_{\text{total}}^{(t)}}{\sum_t \text{Nwkm}^{(t)}}}_{\text{Production + EoL}}
+
\underbrace{\frac{\sum_t \left(\mathbf{e}_{\text{energy}}^{(t)} + \mathbf{e}_{\text{maint}}^{(t)} \times n_{\text{total}}^{(t)}\right)}{\sum_t \text{Nwkm}^{(t)}}}_{\text{Use Phase}}
+
\underbrace{\frac{\sum_d E_{\text{depot},d} / L_{\text{infra}} + \sum_s E_{\text{terminal},s} / L_{\text{infra}}}{\text{Nwkm}_{\text{fleet}}}}_{\text{Charging Infrastructure}}
$$

For an ICEB scenario: the battery term vanishes ($E_{\text{battery}} = 0$, $m_{\text{battery}} = 0$) and the infrastructure term is zero (no BEV charging).

---

## Part 2: Data Model and Calculation

### 2.1 Parameter Storage in eflips-model

LCA parameters are stored in `lca_params` JSONB columns on the relevant eflips-model entities. Each JSONB column has a corresponding hierarchical dataclass that supports `asdict()` for serialization and can be constructed from the eflips-model entity's attributes.

| Entity | `lca_params` stores | Key existing fields used by LCA | Notes |
|--------|--------------------|---------------------------------|-------|
| `VehicleType` | Chassis, motor, use-phase, maintenance params | `empty_mass`, `battery_capacity`, `charging_efficiency`, `energy_source` | |
| `BatteryType` | Battery emission factors and lifetime | `specific_mass` (kg/kWh), `chemistry` (str) | |
| `ChargingPointType` | Charging infra component params | `tco_parameters.useful_life` | Definitively here — not scenario-level |
| `Station` | — (no lca_params; existing fields used directly) | `amount_charging_places`, `power_total` | **Exclude** stations with `Station.depot is not None` |
| `Area` | — (no lca_params; existing fields used directly) | `capacity`, `vehicle_type.energy_source` | **Only** areas where `vehicle_type.energy_source == BATTERY_ELECTRIC` |

### 2.2 VehicleType.lca_params

```python
@dataclass
class VehicleTypeLcaParams:
    # --- Production: Chassis ---
    chassis_emission_factors_per_kg: ImpactVector

    # --- Production: Motor ---
    # For electric motors (energy_source == BATTERY_ELECTRIC):
    motor_rated_power_kw: float
    motor_emission_factors_per_kg: ImpactVector | None      # None if diesel
    motor_power_to_weight_ratio: float | None               # kW/kg; None if diesel

    # For diesel motors (energy_source == DIESEL):
    motor_emission_factors_per_unit: ImpactVector | None    # None if electric
    motor_mass_kg: float  # Electric: derived from power/ratio; Diesel: fixed (1,900 kg)

    # --- Production: Lifetime ---
    vehicle_lifetime_years: float  # Motor + chassis lifetime (default: 12)

    # --- Use Phase: Electricity (BEB) ---
    efficiency_mv_to_lv: float | None           # default: 0.99; None if diesel
    efficiency_lv_ac_to_dc: float | None        # default: 0.95; None if diesel
    electricity_emission_factors_per_kwh: ImpactVector | None  # None if diesel

    # --- Use Phase: Diesel (ICEB) ---
    diesel_emission_factors_production_per_kg: ImpactVector | None  # None if electric
    diesel_emission_factors_combustion_per_kg: ImpactVector | None  # None if electric

    # --- Use Phase: Maintenance ---
    # Key must include the entry matching VehicleType.energy_source.
    # Values are per-vehicle-per-year; scaling by n_total happens in the calculator.
    maintenance_per_year: dict[EnergySource, ImpactVector]

    def __post_init__(self, energy_source: EnergySource) -> None:
        """Validate that only fields consistent with energy_source are populated."""
        if energy_source == EnergySource.BATTERY_ELECTRIC:
            if self.motor_emission_factors_per_unit is not None:
                raise ValueError(
                    "motor_emission_factors_per_unit must be None for BATTERY_ELECTRIC"
                )
            if self.diesel_emission_factors_production_per_kg is not None:
                raise ValueError(
                    "diesel_emission_factors_* must be None for BATTERY_ELECTRIC"
                )
            if EnergySource.BATTERY_ELECTRIC not in self.maintenance_per_year:
                raise ValueError(
                    "maintenance_per_year must contain BATTERY_ELECTRIC for this vehicle type"
                )
        elif energy_source == EnergySource.DIESEL:
            if self.motor_emission_factors_per_kg is not None:
                raise ValueError(
                    "motor_emission_factors_per_kg must be None for DIESEL"
                )
            if self.electricity_emission_factors_per_kwh is not None:
                raise ValueError(
                    "electricity_emission_factors_per_kwh must be None for DIESEL"
                )
            if EnergySource.DIESEL not in self.maintenance_per_year:
                raise ValueError(
                    "maintenance_per_year must contain DIESEL for this vehicle type"
                )
```

Note: `VehicleType.charging_efficiency` (already in eflips-model) is used for $\eta_{\text{battery}}$ in the efficiency chain. It is **not** duplicated in `lca_params`. The `energy_source` argument to `__post_init__` comes from `VehicleType.energy_source` at deserialization time and is not stored in the JSONB.

### 2.3 BatteryType.lca_params

```python
@dataclass
class BatteryTypeLcaParams:
    emission_factors_per_kg: ImpactVector  # Prod+EoL emissions per kg
    battery_lifetime_years: float          # LCA amortization lifetime (default: 8)
```

Existing `BatteryType` fields used:
- `specific_mass` (kg/kWh) → battery mass = `VehicleType.battery_capacity × specific_mass`
- `chemistry` (**str**, e.g. `"LFP"` or `"NMC622"`) → identifies chemistry for selecting emission factors

> **eflips-model change required**: `BatteryType.chemistry` must be migrated from `JSONB` to `Text` (plain string). No structured data beyond the chemistry name is needed.

### 2.4 ChargingPointType.lca_params

Infrastructure LCA parameters are stored definitively on `ChargingPointType.lca_params`. Each `Area` and electrified terminal `Station` has a `charging_point_type` FK; LCA parameters are read from there. If `charging_point_type` is `None` on a relevant `Area` or `Station`, the calculator must raise a clear error.

```python
@dataclass
class ChargingPointTypeLcaParams:
    control_unit_emissions: ImpactVector           # Per 1 control unit (Pattern B)
    power_unit_emissions_per_kg: ImpactVector       # Per kg of power unit (Pattern A)
    power_unit_mass_kg: float                       # kg per power unit (default: 700)
    power_unit_rated_power_kw: float                # kW per power unit, for per-kW scaling
    user_unit_emissions_per_kg: ImpactVector        # Per kg of user unit (Pattern A)
    user_unit_mass_kg: float                        # kg per user unit
    concrete_emissions_per_m3: ImpactVector         # Per m³ of concrete (terminal only)
    foundation_volume_per_point_m3: float           # m³ per charging point (default: 3.96)
    infrastructure_lifetime_years: float            # Lifetime for amortization
```

### 2.5 Simulation Outputs (from eFLIPS)

The following data is obtained from an eFLIPS simulation run, **not** from `lca_params`:

| Data | Per | Notes |
|------|-----|-------|
| Annual energy from battery (kWh) | Vehicle type | **Fleet aggregate** for all ready vehicles of that type |
| Annual diesel consumption (kg) | Vehicle type | **Fleet aggregate** |
| Annual Fahrzeugkilometer | Vehicle type | Fleet aggregate |
| Annual Nutzwagenkilometer | Vehicle type | Fleet aggregate |
| $n_{\text{ready}}^{(t)}$ | Vehicle type | Operationally ready vehicles (not total fleet) |
| $\eta_{\text{avail}}$ | Fleet / type | Technical availability; $n_{\text{total}} = n_{\text{ready}} / \eta_{\text{avail}}$ |
| Peak charging power per depot Area | Per area | Used in infrastructure formula |
| Peak simultaneous vehicle count | Per area / station | Required for oversizing check (derivation TBD) |

### 2.6 Calculation Pipeline

```python
def calculate_lca(scenario: Scenario) -> LcaResult:
    """
    Main entry point. Takes an eFLIPS Scenario and returns per-Nwkm
    emissions broken down by contributor and vehicle type.
    """
    production_results = {}
    use_results = {}

    for vtype in scenario.vehicle_types:
        params = vtype.lca_params  # Deserialized VehicleTypeLcaParams
        battery_type = vtype.battery_type

        # Fleet sizing (shared by both production and maintenance)
        n_ready = scenario.get_ready_vehicles(vtype)
        eta_avail = scenario.get_availability(vtype)
        n_total = n_ready / eta_avail
        nwkm = scenario.get_nwkm(vtype)

        # --- 1. Production + EoL ---
        e_chassis = calculate_chassis_emissions(vtype, params)
        e_motor = calculate_motor_emissions(vtype, params)
        e_battery = calculate_battery_emissions(vtype, battery_type)
        e_prod_annual = amortize_production(e_chassis, e_motor, e_battery, params, battery_type)
        production_results[vtype] = (e_prod_annual * n_total) / nwkm

        # --- 2. Use phase ---
        # e_energy is fleet-aggregate from simulation; e_maint is per-vehicle → scale by n_total
        e_energy = calculate_energy_emissions(vtype, params, scenario)
        e_maint_per_vehicle = params.maintenance_per_year[vtype.energy_source]
        use_results[vtype] = (e_energy + e_maint_per_vehicle * n_total) / nwkm

    # --- 3. Charging infrastructure (BEB only) ---
    e_infra = calculate_infrastructure_emissions(scenario)
    total_nwkm = scenario.total_nwkm

    return LcaResult(
        production=production_results,          # per vehicle type, per Nwkm
        use_phase=use_results,                  # per vehicle type, per Nwkm
        infrastructure=e_infra / total_nwkm,   # fleet-wide, per Nwkm
    )
```

The `calculate_infrastructure_emissions` function:
1. Iterates `Area` objects — skips any where `Area.vehicle_type.energy_source != BATTERY_ELECTRIC`.
2. Iterates `Station` objects — skips any where `Station.depot is not None`.
3. Applies oversizing checks (§1.6.2–1.6.3) using peak vehicle count from simulation.
4. Reads `ChargingPointTypeLcaParams` from `area.charging_point_type.lca_params` (error if None).

### 2.7 Output

The `LcaResult` provides:
- Per-Nwkm emissions broken down by contributor (production, use, infrastructure)
- Per-Nwkm emissions broken down by vehicle type
- Fleet-wide totals
- All as `ImpactVector` instances, accessible by field name

These can be compared between BEB and ICEB scenarios, or used for sensitivity analyses (varying electricity mix, battery lifetime, etc.).

---

## Part 3: openLCA Integration

This module connects to an openLCA IPC server (via the `olca-ipc` Python package) to query ecoinvent processes and automatically populate the `lca_params` JSONB columns.

### 3.1 Ecoinvent Process Mapping

| Parameter | ecoinvent Process | Reference Unit |
|-----------|------------------|----------------|
| LFP battery per kg | `market for battery, Li-ion, LFP, rechargeable` | 1 kg |
| NMC battery per kg | `market for battery, Li-ion, NMC622, rechargeable` | 1 kg |
| Electric motor per kg | `market for electric motor, vehicle` | 1 kg |
| Diesel motor | Custom process: Al (2%) + PE (9%) + Steel (89%) by mass | 1 motor (1,900 kg) |
| Chassis (bus glider) | `bus production \| bus \| Cutoff, U` minus diesel engine | 1 kg (after subtraction) |
| Electricity (DE mix) | `market for electricity, medium voltage` (DE) | 1 kWh |
| Diesel production | `market for diesel` | 1 kg |
| Diesel combustion | `diesel, burned in agricultural machinery` | 1 MJ (scale $\times$45 for 1 kg) |
| Maintenance (ICEB) | `market for maintenance, bus` | 1 bus-year |
| Maintenance (BEB) | `market for maintenance, bus` scaled by literature factor | 1 bus-year (adjusted) |
| Control unit | `Tritium_EV_ChargingStation_ControlUnit` (custom) | 1 unit |
| Power unit | `Tritium_EV_ChargingStation_PowerUnit` (custom) | 1 kg |
| User unit | Custom process for user unit | 1 kg |
| Concrete | Concrete process from ecoinvent | 1 m³ |

> **Verification needed**: The diesel combustion process (`diesel, burned in agricultural machinery`) is used as a proxy. The $\times$45 scaling converts from the 1 MJ reference unit to 1 kg of diesel ($\approx$ 45 MJ/kg lower heating value). A bus-specific combustion process should be used if available in the openLCA database.

### 3.2 LCIA Method Mapping

The 8 impact categories map to the following LCIA methods in ecoinvent/openLCA:

| Field | LCIA Method / Indicator |
|-------|------------------------|
| `gwp` | IPCC GWP 100a (kg CO2 eq) |
| `pm` | Particulate matter formation (kg PM2.5 eq) |
| `pocp` | Photochemical ozone formation (kg NOx eq) |
| `ap` | Acidification (kg SO2 eq) |
| `ep_freshwater` | Eutrophication, freshwater (kg P eq) |
| `ep_marine` | Eutrophication, marine (kg N eq) |
| `fuel` | Fossil resource depletion (kg Oil eq) |
| `water` | Water consumption (m³) |

### 3.3 Populate Workflow

```python
def populate_lca_params(
    vehicle_type: VehicleType,
    battery_type: BatteryType | None,
    ipc_client: olca.Client,
) -> None:
    """
    Queries openLCA via IPC for the relevant processes,
    extracts impact category results, and writes them
    into the lca_params JSONB columns.
    """
    # 1. Query per-kg chassis emission factors
    #    (from bus production process, minus diesel engine, divided by mass)
    # 2. Query motor emission factors based on energy_source:
    #    - BATTERY_ELECTRIC: per-kg from electric motor process
    #    - DIESEL: assemble from Al/PE/Steel material processes
    # 3. If battery_type is set:
    #    - Determine chemistry from battery_type.chemistry (str)
    #    - Query per-kg battery emission factors for that chemistry
    # 4. Query electricity emission factors per kWh (for BEB)
    # 5. Query diesel production + combustion factors (for ICEB)
    # 6. Query maintenance factors for this energy_source
    # 7. Assemble into VehicleTypeLcaParams, validate via __post_init__
    # 8. Write back via SQLAlchemy (asdict() -> JSONB)
```

### 3.4 Custom Processes

Some processes are not available as standard ecoinvent entries and have been created as custom processes within openLCA:

- **Diesel motor**: Assembled from aluminum, polyethylene, and steel production processes weighted by mass fraction (2% Al, 9% PE, 89% steel of 1,900 kg total).
- **Charging infrastructure** (Control Unit, Power Unit): Created by a prior thesis (Tritium system architecture) and stored in an openLCA database; referenced by their custom process names.

The populate function should check for the existence of these custom processes and raise clear errors if they are missing from the connected openLCA instance.
