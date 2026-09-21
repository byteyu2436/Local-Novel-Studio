from pathlib import Path

from app.domain.importing import ImportValidationError, relative_import_storage_path
from app.settings import Settings

TXT_MAX_BYTES = 8_000_000


def original_txt_path(settings: Settings, relative_path: str) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ImportValidationError("txt_path_invalid", "Original file path is invalid.")
    resolved = (settings.data_dir / relative).resolve()
    imports_root = settings.imports_dir.resolve()
    if not resolved.is_relative_to(imports_root):
        raise ImportValidationError("txt_path_invalid", "Original file path is invalid.")
    return resolved


def write_original_txt(
    settings: Settings,
    *,
    source_id: str,
    filename: str,
    payload: bytes,
) -> str:
    """Write original bytes once. Never overwrites an existing snapshot file."""

    relative = relative_import_storage_path(source_id, filename)
    dest = original_txt_path(settings, relative)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        raise ImportValidationError("txt_already_exists", "Original TXT snapshot already exists.")
    partial = dest.with_name(f"{dest.name}.partial")
    partial.write_bytes(payload)
    partial.replace(dest)
    return relative


def remove_original_txt(settings: Settings, relative_path: str) -> None:
    dest = original_txt_path(settings, relative_path)
    dest.unlink(missing_ok=True)
    parent = dest.parent
    if parent.is_dir() and not any(parent.iterdir()):
        parent.rmdir()
