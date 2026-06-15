from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from project_finance_engine import ScenarioRunner, TransactionConfig  # noqa: E402


def test_base_case_senior_sizing_respects_dscr_floor():
    runner = ScenarioRunner(TransactionConfig())
    sized_debt, covenant_table = runner.base_case_senior_debt()
    active_dscr = covenant_table["dscr"].dropna()

    assert sized_debt > 1_000_000_000
    assert np.isclose(active_dscr.min(), runner.config.dscr_floor, atol=0.01)


def test_base_case_retires_senior_debt_by_maturity():
    result = ScenarioRunner().run_all()["CASE 1 - BASE CASE"]
    maturity_balance = result.annual_table.loc[18, "senior_ending_balance"]
    final_balance = result.annual_table.loc[23, "senior_ending_balance"]

    assert maturity_balance < 1.0
    assert final_balance < 1.0
    assert result.summary["senior_default_year_count"] == 0


def test_stress_case_flags_dscr_breaches_and_senior_default():
    result = ScenarioRunner().run_all()["CASE 2 - SUPPLY CHAIN MARGIN COMPRESSION SHOCK"]

    assert not result.covenant_breaches.empty
    assert result.summary["minimum_dscr"] < 1.30
    assert result.summary["senior_default_year_count"] > 0


def test_first_loss_guarantee_reduces_wacc_and_prevents_senior_default():
    results = ScenarioRunner().run_all()
    stress = results["CASE 2 - SUPPLY CHAIN MARGIN COMPRESSION SHOCK"]
    protected = results["CASE 3 - FIRST-LOSS MULTILATERAL GUARANTEE FRAME"]

    assert protected.summary["wacc"] < stress.summary["wacc"]
    assert protected.summary["total_guarantee_drawn"] > 0
    assert protected.summary["senior_default_year_count"] == 0
