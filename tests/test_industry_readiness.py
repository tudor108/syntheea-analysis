import json
from pathlib import Path

from prostate_journey.industry_readiness import (
    FAIL,
    load_contract,
    run_industry_checks,
    validate_contract_structure,
    validate_dataset_contract,
)
from prostate_journey.pipeline import export_tables

ROOT = Path(__file__).resolve().parents[1]


def _statuses(results):
    return {result.check_id: result for result in results}


def test_machine_readable_contract_is_complete():
    contract_path = ROOT / "contracts/analytical_data_contract.yaml"
    contract = load_contract(contract_path)
    results = validate_contract_structure(contract, str(contract_path))

    assert all(result.status != FAIL for result in results), results
    assert len(contract["tables"]) == 19
    assert len(contract["model_populations"]) == 4


def test_dataset_contract_gates_keys_chronology_denominators_and_leakage(
    generated_tables, tmp_path
):
    dataset = tmp_path / "analytical_dataset"
    export_tables(generated_tables, dataset)
    contract = load_contract(ROOT / "contracts/analytical_data_contract.yaml")

    results = _statuses(validate_dataset_contract(dataset, contract))

    assert all(result.status != FAIL for result in results.values()), results
    assert results["dataset.primary_keys"].failure_count == 0
    assert results["dataset.foreign_keys"].failure_count == 0
    assert results["dataset.temporal_invariants"].failure_count == 0
    assert results["analysis.initiation_denominator"].failure_count == 0
    assert results["analysis.persistence_denominator"].failure_count == 0
    assert results["analysis.censoring_semantics"].failure_count == 0
    assert results["analysis.leakage_controls"].failure_count == 0


def test_contract_gate_fails_closed_on_corrupt_foreign_key(generated_tables, tmp_path):
    altered = {name: frame.copy() for name, frame in generated_tables.items()}
    altered["diagnosis"].loc[altered["diagnosis"].index[0], "patient_id"] = "MISSING-PATIENT"
    dataset = tmp_path / "analytical_dataset"
    export_tables(altered, dataset)
    contract = load_contract(ROOT / "contracts/analytical_data_contract.yaml")

    results = _statuses(validate_dataset_contract(dataset, contract))

    assert results["dataset.foreign_keys"].status == FAIL
    assert results["dataset.foreign_keys"].failure_count >= 1


def test_source_only_industry_check_writes_machine_readable_report(tmp_path):
    output = tmp_path / "industry.json"

    payload = run_industry_checks(ROOT, allow_missing_release=True, output_path=output)

    assert payload["overall_status"] == "PASS"
    assert payload["formal_compliance_claim"] is False
    assert payload["summary"]["skipped"] == 1
    assert json.loads(output.read_text(encoding="utf-8"))["overall_status"] == "PASS"
