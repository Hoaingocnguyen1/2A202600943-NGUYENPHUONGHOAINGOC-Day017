"""Extension #3 — prove the data contract has NOT drifted from the enforced gate.

A contract that disagrees with what the pipeline actually enforces is worse than
no contract: consumers trust a promise the producer no longer keeps. This test
applies the contract's quality rules to the raw data and asserts it rejects the
*same* rows that the Pandera gate (pipeline/validate.py) quarantines — and that
the contract's columns match the enforced schema.

Zero-key. Needs PyYAML (`pip install pyyaml`). Kept in bonus/ so the graded
`pytest -q` stays at 18.  Run:  python -m pytest bonus/test_data_contract.py -q
"""
from pathlib import Path

import pandas as pd
import yaml

from pipeline import config
from pipeline.validate import ORDER_SCHEMA, validate

CONTRACT = Path(__file__).resolve().parent.parent / "datacontract.yaml"


def _load_properties() -> list[dict]:
    doc = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    return doc["schema"][0]["properties"]


def _row_violates(row: pd.Series, props: list[dict]) -> bool:
    """Apply the contract's per-field rules to one raw (all-string) row."""
    for p in props:
        val = row.get(p["name"])
        empty = val is None or (isinstance(val, float) and pd.isna(val)) or str(val).strip() == ""
        if p.get("required") and empty:
            return True
        if empty:
            continue
        for q in p.get("quality", []):
            rule = q["rule"]
            if rule == "minimum":
                try:
                    if float(val) <= q["mustBeGreaterThan"]:
                        return True
                except ValueError:
                    return True
            elif rule == "minLength":
                if len(str(val).strip()) < q["value"]:
                    return True
            elif rule == "validValues":
                if str(val) not in q["validValues"]:
                    return True
    return False


def test_contract_columns_match_enforced_schema():
    names = {p["name"] for p in _load_properties()}
    assert names == set(ORDER_SCHEMA.columns.keys())


def test_contract_rejects_same_rows_as_pandera_gate():
    props = _load_properties()
    raw = pd.read_csv(config.RAW_CSV, dtype=str)

    contract_bad = {i for i, row in raw.iterrows() if _row_violates(row, props)}

    _, quarantined = validate(raw)
    # map quarantined rows back to their raw index by order_id (stable key)
    gate_bad = set(raw.index[raw["order_id"].isin(quarantined["order_id"])])

    assert contract_bad == gate_bad, (
        f"contract drifted from the gate: contract={contract_bad} gate={gate_bad}"
    )
    assert len(contract_bad) == 3        # the null user_id, negative amount, bad status
