"""Dataset instance persistence / reload from disk."""

import json
from pathlib import Path

import dataset_builder
import error
import pr_collection
import pydantic


def load_dataset_instances(datasets_root: Path) -> tuple[dataset_builder.DatasetInstance, ...]:
    """Reload every materialized dataset instance under `datasets_root`.

    Each child directory that contains a task metadata file is treated as an
    instance root. Results are sorted by directory name for deterministic
    downstream ordering.
    """
    if not datasets_root.is_dir():
        raise error.ConstraintCatalogError(f"Dataset root not found: {datasets_root}")
    instance_roots = sorted(
        (child for child in datasets_root.iterdir() if (child / dataset_builder.TASK_FILENAME).is_file()),
        key=lambda path: path.name,
    )
    return tuple(_load_single_instance(root) for root in instance_roots)


def _load_single_instance(instance_root: Path) -> dataset_builder.DatasetInstance:
    task_path = instance_root / dataset_builder.TASK_FILENAME
    try:
        document = json.loads(task_path.read_text(encoding="utf-8"))
        detail = pr_collection.PullRequestDetail.model_validate(document)
    except (OSError, json.JSONDecodeError, pydantic.ValidationError) as validation_error:
        raise error.ConstraintCatalogError(
            f"Malformed dataset instance at {instance_root}",
        ) from validation_error
    return dataset_builder.DatasetInstance(detail=detail, root=instance_root)
