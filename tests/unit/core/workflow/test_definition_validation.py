import pytest

from src.core.workflow import (
    ValidationErrorCode,
    WorkflowDefinition,
    WorkflowValidationError,
)

from .conftest import FakeNode


def test_valid_definition_loads_and_derives_edges():
    clean = FakeNode("clean", requires=("source",), provides=("md",))
    chunk = FakeNode("chunk", requires=("md",), provides=("chunks",))

    definition = WorkflowDefinition.from_nodes(
        [clean, chunk],
        name="parse",
        initial_products=("source",),
    )

    assert definition.edges() == {("clean", "chunk")}
    assert definition.topo_order() == ["clean", "chunk"]
    assert clean.run_count == 0
    assert chunk.run_count == 0


def test_cycle_is_rejected_at_load_time():
    with pytest.raises(WorkflowValidationError) as exc_info:
        WorkflowDefinition.from_nodes(
            [
                FakeNode("A", requires=("y",), provides=("x",)),
                FakeNode("B", requires=("x",), provides=("y",)),
            ]
        )

    assert exc_info.value.code == ValidationErrorCode.CYCLE


def test_duplicate_producer_is_rejected_with_product_detail():
    with pytest.raises(WorkflowValidationError) as exc_info:
        WorkflowDefinition.from_nodes(
            [
                FakeNode("A", provides=("chunks",)),
                FakeNode("B", provides=("chunks",)),
            ]
        )

    assert exc_info.value.code == ValidationErrorCode.DUPLICATE_PRODUCER
    assert "chunks" in exc_info.value.detail


def test_dangling_requires_is_rejected_with_product_detail():
    with pytest.raises(WorkflowValidationError) as exc_info:
        WorkflowDefinition.from_nodes([FakeNode("chunk", requires=("md",), provides=("chunks",))])

    assert exc_info.value.code == ValidationErrorCode.DANGLING_REQUIRES
    assert "md" in exc_info.value.detail


def test_allow_failure_provider_cannot_feed_required_downstream():
    with pytest.raises(WorkflowValidationError) as exc_info:
        WorkflowDefinition.from_nodes(
            [
                FakeNode("opt", provides=("x",), allow_failure=True),
                FakeNode("down", requires=("x",)),
            ]
        )

    assert exc_info.value.code == ValidationErrorCode.ALLOW_FAILURE_PROVIDES_REQUIRED
    assert "opt" in exc_info.value.detail
    assert "x" in exc_info.value.detail
