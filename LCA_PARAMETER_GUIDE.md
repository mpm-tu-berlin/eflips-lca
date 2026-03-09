# LCA Parameter Guide for eflips-lca

This guide describes every environmental impact value and engineering constant that the eflips-lca software needs. It is written for LCA practitioners who will query openLCA / ecoinvent and provide the resulting numbers.

---

## 1. What this software does

eflips-lca computes the life-cycle environmental impact of electric bus (BEB) and diesel bus (ICEB) fleets. It follows **ISO 14040/14044** with a **Cradle-to-Grave** system boundary.

The **functional unit** is the **Nutzwagenkilometer (Nwkm)** — one kilometre driven by a bus in revenue service, regardless of passenger load. All results are expressed as environmental impact *per Nwkm*, enabling direct comparison between BEB and ICEB scenarios.

The software combines two kinds of input:

- **Simulation outputs** from eFLIPS (vehicle-km, revenue-km, fleet size, charging power). *You do not need to provide these.*
- **LCA parameters** — emission factors and engineering constants. *This is what you provide.*

The life cycle is split into three contributors:

| Contributor | Covers | Applies to |
|---|---|---|
| **Production + End-of-Life** | Manufacturing and disposal of chassis, motor, battery | BEB and ICEB |
| **Use Phase** | Energy consumption (electricity or diesel) and maintenance | BEB and ICEB |
| **Charging Infrastructure** | Manufacturing and disposal of charging equipment | BEB only |

---

## 2. Impact categories

Every emission factor value you deliver must contain results for **all 8 categories** listed below. In the software these are bundled into a data structure called an "ImpactVector". Think of it as a row with 8 columns.

| # | Category | LCIA Method / Indicator | Unit | Internal field name |
|---|---|---|---|---|
| 1 | Global warming potential (100a) | IPCC GWP 100a | kg CO2 eq | `gwp` |
| 2 | Particulate matter formation | Particulate matter formation | kg PM2.5 eq | `pm` |
| 3 | Photochemical ozone creation | Photochemical ozone formation | kg NOx eq | `pocp` |
| 4 | Acidification | Acidification | kg SO2 eq | `ap` |
| 5 | Freshwater eutrophication | Eutrophication, freshwater | kg P eq | `ep_freshwater` |
| 6 | Marine eutrophication | Eutrophication, marine | kg N eq | `ep_marine` |
| 7 | Fossil resource depletion | Fossil resource depletion | kg Oil eq | `fuel` |
| 8 | Water consumption | Water consumption | m3 | `water` |

When we say "deliver an ImpactVector for process X", we mean: run process X in openLCA and report the result for each of these 8 indicators.

---

## 3. Emission factor values we need from openLCA

This section lists every ImpactVector the software requires. Each entry specifies what to query, in what reference unit, and any post-processing. The entries are grouped by where they are used.

### 3.1 Chassis (applies to BEB and ICEB)

**Field name:** `chassis_emission_factors_per_kg`
**Reference unit:** 1 kg of bus chassis (the "glider" — everything that is neither motor nor energy storage)
**What to query:** The ecoinvent process `bus production | bus | Cutoff, U` (models an 11-tonne diesel bus).

**Post-processing required:**
1. Run the bus production process for one complete bus.
2. Subtract the contribution of the diesel engine (1,900 kg) from the total impact.
3. Divide the remaining impact by the bus mass minus the engine mass (i.e., the chassis mass of the reference bus).

This gives you **per-kg emission factors for the chassis**, which the software will scale linearly to the actual chassis mass of any bus type.

**Formula context:** `chassis_mass = curb_weight - motor_mass - battery_mass`, then `E_chassis = chassis_mass * chassis_emission_factors_per_kg`.

---

### 3.2 Electric motor (BEB only)

**Field name:** `motor_emission_factors_per_kg`
**Reference unit:** 1 kg of electric motor
**What to query:** `market for electric motor, vehicle` in ecoinvent.

No post-processing needed. The software derives the motor mass from the rated power and a power-to-weight ratio, then multiplies by this per-kg factor.

**Formula context:** `motor_mass = rated_power_kw / power_to_weight_ratio`, then `E_motor = motor_mass * motor_emission_factors_per_kg`.

---

### 3.3 Diesel motor (ICEB only)

**Field name:** `motor_emission_factors_per_unit`
**Reference unit:** 1 complete diesel motor (1,900 kg)
**What to query:** There is no single ecoinvent process. Assemble a custom process from material production processes weighted by mass fraction:

| Material | Mass fraction | Ecoinvent process |
|---|---|---|
| Aluminium | 2% (38 kg) | Aluminium production process |
| Polyethylene | 9% (171 kg) | Polyethylene production process |
| Steel | 89% (1,691 kg) | Steel production process |

Run each material process for its respective mass, sum the 8-category impacts, and report the total as one ImpactVector for the complete motor.

**Formula context:** `E_motor = motor_emission_factors_per_unit` (flat per-unit value, not scaled by mass).

---

### 3.4 Battery (BEB only)

**Field name:** `emission_factors_per_kg` (on BatteryType, not VehicleType)
**Reference unit:** 1 kg of battery pack
**What to query:** Depends on the cell chemistry:

| Chemistry | Ecoinvent process |
|---|---|
| LFP | `market for battery, Li-ion, LFP, rechargeable` |
| NMC622 | `market for battery, Li-ion, NMC622, rechargeable` |

No post-processing needed. Provide one ImpactVector per chemistry in use.

**Formula context:** `battery_mass = battery_capacity_kWh * specific_mass_kg_per_kWh`, then `E_battery = battery_mass * emission_factors_per_kg`.

---

### 3.5 Grid electricity (BEB only)

**Field name:** `electricity_emission_factors_per_kwh`
**Reference unit:** 1 kWh of medium-voltage grid electricity
**What to query:** `market for electricity, medium voltage` for the relevant country (Germany by default).

These factors are **year-specific** because the electricity generation mix changes over time. If you are modelling a future scenario, use the projected mix for that year.

No post-processing needed.

**Formula context:** The software first calculates how much grid electricity is consumed (accounting for transformer, rectifier, and battery charging losses), then multiplies by this factor. You do *not* need to account for efficiency losses — the software handles that.

---

### 3.6 Diesel fuel — well-to-tank (ICEB only)

**Field name:** `diesel_emission_factors_production_per_kg`
**Reference unit:** 1 kg of diesel fuel produced and delivered
**What to query:** `market for diesel` in ecoinvent.

No post-processing needed. This covers extraction, refining, and distribution — everything up to the point of combustion.

**Formula context:** Combined with combustion factors (below) and multiplied by annual diesel consumption in kg.

---

### 3.7 Diesel fuel — combustion / tank-to-wheel (ICEB only)

**Field name:** `diesel_emission_factors_combustion_per_kg`
**Reference unit:** 1 kg of diesel burned

**What to query:** `diesel, burned in agricultural machinery` in ecoinvent.

**Post-processing required:** This ecoinvent process has a reference unit of **1 MJ**. Since 1 kg of diesel has a lower heating value of approximately 45 MJ, **multiply all impact results by 45** to convert from per-MJ to per-kg.

> **Note:** This is a proxy process. If a bus-specific diesel combustion process is available in your openLCA database, use that instead and adjust the reference unit accordingly.

**Formula context:** `e_diesel_per_kg = diesel_production_per_kg + diesel_combustion_per_kg`, then multiplied by annual diesel consumption.

---

### 3.8 Maintenance — ICEB

**Field name:** `maintenance_per_year` (keyed by energy source DIESEL)
**Reference unit:** 1 bus maintained for 1 year
**What to query:** `market for maintenance, bus` in ecoinvent.

No post-processing needed. This covers replacement parts (oil, filters, brakes, tires, coolant, etc.) for one conventional diesel bus for one year.

---

### 3.9 Maintenance — BEB

**Field name:** `maintenance_per_year` (keyed by energy source BATTERY_ELECTRIC)
**Reference unit:** 1 bus maintained for 1 year

**What to query:** Start from `market for maintenance, bus` (same as ICEB). Then apply a **literature-based reduction factor** — typically around 0.75 (i.e., BEB maintenance is approximately 75% of ICEB maintenance) due to:
- No engine oil changes
- Reduced brake wear (regenerative braking)
- Fewer mechanical components

Document the reduction factor and its source.

---

### 3.10 Charging infrastructure — control unit

**Field name:** `control_unit_emissions`
**Reference unit:** 1 complete control unit
**What to query:** `Tritium_EV_ChargingStation_ControlUnit` — a **custom process** that must exist in your openLCA database. It was created for the Tritium charging system architecture.

No post-processing needed.

**Formula context:** The software assigns exactly one control unit per depot charging area and one per electrified terminal station.

---

### 3.11 Charging infrastructure — power unit

**Field name:** `power_unit_emissions_per_kg`
**Reference unit:** 1 kg of power unit
**What to query:** `Tritium_EV_ChargingStation_PowerUnit` — a **custom process** that must exist in your openLCA database.

No post-processing needed.

**Formula context:** The software derives a per-kW factor from these per-kg emissions: `e_per_kW = (power_unit_mass_kg * e_per_kg) / power_unit_rated_power_kw`, then scales by the peak charging power at each location.

---

### 3.12 Charging infrastructure — user unit (plug/pantograph)

**Field name:** `user_unit_emissions_per_kg`
**Reference unit:** 1 kg of user unit
**What to query:** Custom process for the charging connector / pantograph unit. This may be a custom openLCA process or assembled from material production processes, depending on what is available.

No post-processing needed.

**Formula context:** `e_per_plug = user_unit_mass_kg * e_per_kg`, then scaled by the number of charging points.

---

### 3.13 Charging infrastructure — concrete foundation

**Field name:** `concrete_emissions_per_m3`
**Reference unit:** 1 m3 of concrete
**What to query:** `market for concrete, normal` in ecoinvent.

No post-processing needed.

**Formula context:** Used only for terminal (Endhaltestelle) chargers, not depot chargers. Multiplied by the foundation volume per charging point (default 3.96 m3 per point).

---

## 4. Scalar / literature parameters

These values typically come from datasheets, literature, or engineering knowledge — not from openLCA. They are listed here for completeness.

### 4.1 Vehicle parameters

| Parameter | Unit | Default | Applies to | Description |
|---|---|---|---|---|
| `motor_rated_power_kw` | kW | *(from datasheet)* | BEB and ICEB | Rated power of the traction motor |
| `motor_power_to_weight_ratio` | kW/kg | *(from literature)* | BEB only | Used to derive electric motor mass from rated power |
| `motor_mass_kg` | kg | 1,900 | ICEB only | Mass of the diesel engine (fixed assumption) |
| `vehicle_lifetime_years` | years | 12 | BEB and ICEB | Operating lifetime for amortising chassis + motor |
| `average_consumption_kwh_per_km` | kWh/km | *(from simulation/datasheet)* | BEB and ICEB | Average energy consumption used by LCA (not worst-case) |
| `diesel_consumption_kg_per_km` | kg/km | *(from simulation/datasheet)* | ICEB only | Average diesel consumption per km |
| `efficiency_mv_to_lv` | dimensionless | 0.99 | BEB only | Medium-to-low voltage transformer efficiency |
| `efficiency_lv_ac_to_dc` | dimensionless | 0.95 | BEB only | AC/DC rectifier efficiency |

> **Note on consumption values:** The software intentionally uses *average* consumption for LCA, not worst-case simulation values. This is because LCA assesses typical operation, not peak demand.

### 4.2 Battery parameters

| Parameter | Unit | Default | Description |
|---|---|---|---|
| `battery_lifetime_years` | years | 8 | Battery lifetime for amortisation (may differ from vehicle lifetime) |

> Battery capacity (kWh) and specific mass (kg/kWh) are already stored in the eflips-model database. You do not need to provide them.

### 4.3 Charging infrastructure parameters

| Parameter | Unit | Default | Description |
|---|---|---|---|
| `power_unit_mass_kg` | kg | 700 | Mass of one power unit cabinet |
| `power_unit_rated_power_kw` | kW | *(from datasheet)* | Rated power of one power unit (needed to convert per-kg to per-kW) |
| `user_unit_mass_kg` | kg | *(from datasheet)* | Mass of one user unit (plug or pantograph) |
| `foundation_volume_per_point_m3` | m3 | 3.96 | Concrete foundation volume per terminal charging point |
| `infrastructure_lifetime_years` | years | 20 | Lifetime for amortising charging equipment |

---

## 5. Special cases and warnings

### 5.1 Chassis derivation from bus production process

The ecoinvent process `bus production | bus | Cutoff, U` models a *complete* 11-tonne diesel bus including the engine. To obtain per-kg chassis factors:
1. Determine the total impact of the complete bus process.
2. Determine the impact of the diesel engine (using the custom assembled diesel motor process from Section 3.3).
3. Subtract the engine impact from the bus impact.
4. Divide by the chassis mass of the reference bus (total mass minus engine mass = 11,000 kg - 1,900 kg = 9,100 kg).

The result is a per-kg chassis emission factor that the software scales to the actual chassis mass of any bus.

### 5.2 Diesel combustion — proxy process and scaling

The ecoinvent process `diesel, burned in agricultural machinery` is a proxy because there is no bus-specific diesel combustion process in standard ecoinvent. Its reference unit is 1 MJ, so all results must be multiplied by ~45 (lower heating value of diesel in MJ/kg). If a bus-specific combustion process becomes available, it should replace this proxy.

### 5.3 Custom processes in openLCA

The following processes are **not part of standard ecoinvent** and must exist as custom entries in the connected openLCA database:

- `Tritium_EV_ChargingStation_ControlUnit` — one complete control unit
- `Tritium_EV_ChargingStation_PowerUnit` — per kg of power unit

These were created for the Tritium charging system architecture. If they are missing, the charging infrastructure assessment cannot run.

### 5.4 Diesel motor — custom assembly

The diesel motor is not a single ecoinvent process but an assembly of three material production processes weighted by mass (2% Al, 9% PE, 89% steel of 1,900 kg total). This should be created as a custom process in openLCA or computed manually by summing the individual material impacts.

### 5.5 BEB maintenance reduction

BEB maintenance emissions are derived from the ICEB maintenance process (`market for maintenance, bus`) with a literature-based reduction factor. The exact factor should be documented with its source. A common value is approximately 0.75 (25% reduction).

---

## 6. Delivery format

Data is delivered as a **JSON file** conforming to the `OpenLcaData` schema (see `eflips/lca/open_lca_data.py`). The JSON file is stored in the `data/` directory with naming convention `openlca_data_<descriptive_name>.json` and is tracked in git.

The JSON file contains:
- **Metadata**: ecoinvent version, LCIA method set, description, creation timestamp
- **14 ImpactVectors**: each with 8 impact category values (see table below)
- **Scalar parameters**: all values from Section 4
- **Year-specific electricity**: emission factors per kWh for multiple calendar years (the software interpolates between defined years)

For each ImpactVector, provide the 8 impact category values:

| Process | Reference unit | gwp (kg CO2 eq) | pm (kg PM2.5 eq) | pocp (kg NOx eq) | ap (kg SO2 eq) | ep_freshwater (kg P eq) | ep_marine (kg N eq) | fuel (kg Oil eq) | water (m3) |
|---|---|---|---|---|---|---|---|---|---|
| Chassis per kg | 1 kg | ... | ... | ... | ... | ... | ... | ... | ... |
| Electric motor per kg | 1 kg | ... | ... | ... | ... | ... | ... | ... | ... |
| Diesel motor per unit | 1 motor | ... | ... | ... | ... | ... | ... | ... | ... |
| LFP battery per kg | 1 kg | ... | ... | ... | ... | ... | ... | ... | ... |
| NMC622 battery per kg | 1 kg | ... | ... | ... | ... | ... | ... | ... | ... |
| Electricity (DE mix) per kWh | 1 kWh | ... | ... | ... | ... | ... | ... | ... | ... |
| Diesel production per kg | 1 kg | ... | ... | ... | ... | ... | ... | ... | ... |
| Diesel combustion per kg | 1 kg (after x45) | ... | ... | ... | ... | ... | ... | ... | ... |
| Maintenance ICEB per year | 1 bus-year | ... | ... | ... | ... | ... | ... | ... | ... |
| Maintenance BEB per year | 1 bus-year (adjusted) | ... | ... | ... | ... | ... | ... | ... | ... |
| Control unit | 1 unit | ... | ... | ... | ... | ... | ... | ... | ... |
| Power unit per kg | 1 kg | ... | ... | ... | ... | ... | ... | ... | ... |
| User unit per kg | 1 kg | ... | ... | ... | ... | ... | ... | ... | ... |
| Concrete per m3 | 1 m3 | ... | ... | ... | ... | ... | ... | ... | ... |

**Total: 14 ImpactVectors** (rows) with **8 categories** (columns) each = **112 values** to provide, plus the scalar parameters from Section 4.

### 6.1 Electricity: year-specific values

The electricity emission factor must be provided for **multiple calendar years** to account for changes in the grid mix. In the JSON file, the `electricity_per_kwh` field maps year strings to ImpactVectors:

```json
"electricity_per_kwh": {
    "2025": {"gwp": 0.434, "pm": ..., ...},
    "2030": {"gwp": 0.350, "pm": ..., ...},
    "2035": {"gwp": 0.250, "pm": ..., ...}
}
```

The software linearly interpolates between defined years and clamps (with a warning) outside the defined range. Provide data points for at least the years covered by your scenarios.

### 6.2 Metadata

Along with the emission factors and scalar parameters, the JSON file includes:
- `ecoinvent_version`: The ecoinvent database version used
- `lcia_method_set`: The LCIA method set and version
- `description`: Any assumptions or deviations from the processes listed above
- `created_at`: ISO 8601 timestamp of creation

Sources for literature-based values (reduction factors, efficiencies, lifetimes, masses) should be documented in the `description` field or in accompanying documentation.

---

## 7. Summary checklist

- [ ] Chassis per-kg factors (derived from bus production minus diesel engine)
- [ ] Electric motor per-kg factors
- [ ] Diesel motor per-unit factors (assembled from Al/PE/Steel)
- [ ] LFP battery per-kg factors
- [ ] NMC622 battery per-kg factors (if NMC chemistry is used)
- [ ] Grid electricity per-kWh factors (year-specific if needed)
- [ ] Diesel production per-kg factors (well-to-tank)
- [ ] Diesel combustion per-kg factors (tank-to-wheel, after x45 scaling)
- [ ] ICEB maintenance per bus-year
- [ ] BEB maintenance per bus-year (with documented reduction factor)
- [ ] Control unit per unit (custom Tritium process)
- [ ] Power unit per kg (custom Tritium process)
- [ ] User unit per kg
- [ ] Concrete per m3
- [ ] All scalar parameters from Section 4 confirmed or adjusted
- [ ] Ecoinvent version and LCIA methods documented
