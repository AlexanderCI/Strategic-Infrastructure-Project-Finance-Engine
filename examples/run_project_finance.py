"""Run the three-case deterministic project finance model."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from project_finance_engine import ScenarioRunner, TerminalReport  # noqa: E402


def main() -> None:
    runner = ScenarioRunner()
    results = runner.run_all()
    TerminalReport().print_all(results)


if __name__ == "__main__":
    main()
