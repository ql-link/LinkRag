import src.core.vector_storage as vector_storage
from pathlib import Path


def test_should_expose_pipeline_modules_without_legacy_service_aliases_when_importing_public_api():
    assert vector_storage.VectorStoragePipeline.__module__.endswith(".pipeline")
    assert vector_storage.VectorStorageManagementPipeline.__module__.endswith(
        ".management_pipeline"
    )
    assert vector_storage.VectorStorageCompensationPipeline.__module__.endswith(
        ".compensation_pipeline"
    )

    assert not hasattr(vector_storage, "ChunkStorageService")
    assert not hasattr(vector_storage, "ChunkManagementService")
    assert not hasattr(vector_storage, "ChunkCompensationService")


def test_should_not_keep_legacy_services_directory_when_pipeline_modules_are_the_source():
    assert not Path("src/core/vector_storage/services").exists()


def test_should_not_keep_storage_adapters_in_orchestration_module():
    orchestration_dir = Path("src/core/vector_storage")

    assert not (orchestration_dir / "bucket_router.py").exists()
    assert not (orchestration_dir / "point_factory.py").exists()
    assert not (orchestration_dir / "stores").exists()
