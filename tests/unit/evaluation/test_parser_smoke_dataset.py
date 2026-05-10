from src.evaluation.datasets.loader import FileSystemDataset


def test_parser_smoke_dataset_should_load_all_pdf_samples_with_ground_truth():
    dataset = FileSystemDataset("tests/evaluation_datasets/parser_smoke/manifest.yaml")

    samples = list(dataset.iter_samples())

    assert dataset.name == "parser_smoke"
    assert dataset.sample_count == 13
    assert samples
    assert all(sample.file_type == "pdf" for sample in samples)
    assert all(sample.file_path and sample.file_path.endswith(".pdf") for sample in samples)
    assert all(sample.ground_truth.get("markdown") for sample in samples)
