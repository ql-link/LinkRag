from src.evaluation.runners.pipeline import EvalPipeline


def test_pipeline_should_load_dataset_version_and_split():
    pipeline = EvalPipeline.from_yaml("configs/eval/parser_only.yaml")

    assert pipeline.dataset_name == "parser_smoke"
    assert pipeline.dataset_version == "latest"
    assert pipeline.dataset_split == "test"
