from __future__ import annotations

from pathlib import Path

import pytest


INTEGRATION_DIR = Path("tests/integration")


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="collect and run integration tests under tests/integration",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "unit: fast tests with mocked dependencies")
    config.addinivalue_line(
        "markers",
        "integration: tests that require real services, network, or full application wiring",
    )
    config.addinivalue_line(
        "markers",
        "connectivity: smoke checks for external infrastructure connectivity",
    )


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool:
    if config.getoption("--run-integration"):
        return False

    try:
        relative_path = collection_path.relative_to(Path.cwd())
    except ValueError:
        relative_path = collection_path

    return INTEGRATION_DIR in relative_path.parents or relative_path == INTEGRATION_DIR


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        test_path = Path(str(item.fspath))

        if INTEGRATION_DIR in test_path.parents:
            item.add_marker(pytest.mark.integration)
        else:
            item.add_marker(pytest.mark.unit)

        if test_path.name == "test_connectivity.py":
            item.add_marker(pytest.mark.connectivity)
