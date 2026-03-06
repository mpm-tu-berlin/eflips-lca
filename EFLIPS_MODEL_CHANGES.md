# Required Changes to eflips-model

This document describes the modifications needed in the
[eflips-model](https://github.com/mpm-tu-berlin/eflips-model) package
to support eflips-lca.

All changes are in **`eflips/model/general.py`**.

---

## 1. Add `lca_params` JSONB column to `VehicleType`

**Location**: After the `tco_parameters` column (around line 617).

```python
lca_params: Mapped[Dict[str, Any]] = mapped_column(
    postgresql.JSONB().with_variant(JSON, "sqlite"),  # type: ignore
    nullable=True,
)
"""LCA (Life Cycle Assessment) parameters for this vehicle type.

Stored as a JSON object. Use ``eflips.lca.VehicleTypeLcaParams.from_dict()``
to deserialise and ``.to_dict()`` to serialise. Contains chassis, motor,
use-phase, and maintenance emission factors.

See the eflips-lca design document for the full schema.
"""
```

---

## 2. Add `lca_params` JSONB column to `BatteryType`

**Location**: After the `tco_parameters` column (around line 748).

```python
lca_params: Mapped[Dict[str, Any]] = mapped_column(
    postgresql.JSONB().with_variant(JSON, "sqlite"),  # type: ignore
    nullable=True,
)
"""LCA parameters for this battery type.

Stored as a JSON object. Use ``eflips.lca.BatteryTypeLcaParams.from_dict()``
to deserialise. Contains emission factors per kg and battery lifetime.
"""
```

---

## 3. Add `lca_params` JSONB column to `ChargingPointType`

**Location**: After the `tco_parameters` column (around line 1445).

```python
lca_params: Mapped[Dict[str, Any]] = mapped_column(
    postgresql.JSONB().with_variant(JSON, "sqlite"),  # type: ignore
    nullable=True,
)
"""LCA parameters for this charging point type.

Stored as a JSON object. Use
``eflips.lca.ChargingPointTypeLcaParams.from_dict()`` to deserialise.
Contains control/power/user unit emission factors, concrete parameters,
and infrastructure lifetime.
"""
```

---

## 4. Migrate `BatteryType.chemistry` from JSONB to Text

**Location**: Lines 716-718.

**Current**:
```python
chemistry: Mapped[Dict[str, Any]] = mapped_column(
    postgresql.JSONB().with_variant(JSON, "sqlite")  # type: ignore
)
```

**New**:
```python
chemistry: Mapped[str] = mapped_column(Text)
"""The chemistry of the battery as a plain string, e.g. ``'LFP'`` or ``'NMC622'``."""
```

eflips-lca uses this string to select the correct battery emission
factors from openLCA.

---

## 5. Alembic Migration

Create a new Alembic migration (e.g. version `v10.2.0`) that:

1. Adds nullable `lca_params` JSONB columns to `VehicleType`,
   `BatteryType`, and `ChargingPointType`.

2. Migrates `BatteryType.chemistry` from JSONB to Text. Example:

```python
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

def upgrade() -> None:
    op.add_column(
        "VehicleType",
        sa.Column("lca_params", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "BatteryType",
        sa.Column("lca_params", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "ChargingPointType",
        sa.Column("lca_params", postgresql.JSONB(), nullable=True),
    )

    # Migrate chemistry: JSONB -> Text
    # Adjust the conversion expression based on how chemistry data is
    # currently stored (e.g. as a JSON string, or as {"type": "LFP"}).
    op.add_column(
        "BatteryType",
        sa.Column("chemistry_new", sa.Text(), nullable=True),
    )
    op.execute(
        'UPDATE "BatteryType" SET chemistry_new = chemistry::text'
    )
    op.drop_column("BatteryType", "chemistry")
    op.alter_column(
        "BatteryType", "chemistry_new", new_column_name="chemistry"
    )


def downgrade() -> None:
    # Reverse the chemistry migration
    op.add_column(
        "BatteryType",
        sa.Column(
            "chemistry_old",
            postgresql.JSONB(),
            nullable=True,
        ),
    )
    op.execute(
        'UPDATE "BatteryType" SET chemistry_old = to_jsonb(chemistry)'
    )
    op.drop_column("BatteryType", "chemistry")
    op.alter_column(
        "BatteryType", "chemistry_old", new_column_name="chemistry"
    )

    op.drop_column("ChargingPointType", "lca_params")
    op.drop_column("BatteryType", "lca_params")
    op.drop_column("VehicleType", "lca_params")
```

---

## 6. Verify `Scenario.clone()`

The `Scenario.clone()` method deep-copies all mapped columns
automatically. After adding `lca_params`, verify that cloning a
scenario correctly copies the JSONB values to the new entities. No code
change should be needed, but confirm with a test.
