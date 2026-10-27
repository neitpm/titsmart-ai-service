"""Sample loader module for loading and validating offline JSON data."""
import json
import logging
from pathlib import Path
from typing import List, Type, TypeVar, Optional, Dict, Any, Generic
from pydantic import BaseModel, ValidationError

from titsmart_ai.config import settings
from titsmart_ai.domain.models import Project, Task, FieldLog, Issue, DocumentTrack

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LoadResult(BaseModel, Generic[T]):
    """Kết quả nạp dữ liệu chi tiết kèm số lượng và danh sách lỗi."""
    items: List[T] = []
    total_records: int = 0
    loaded: int = 0
    skipped: int = 0
    errors: List[str] = []


class SampleDataLoader:
    """
    Loader chuyên đọc và kiểm định dữ liệu mẫu dạng JSON.
    Hỗ trợ xử lý ngoại lệ: file không tồn tại, JSON hỏng, bản ghi thiếu trường / schema drift.
    Cung cấp thống kê chi tiết số bản ghi nạp được và danh sách lỗi.
    """

    def __init__(self, sample_dir: Optional[Path] = None):
        self.sample_dir = sample_dir or settings.SAMPLE_DATA_DIR

    def _load_and_validate(self, filename: str, model_cls: Type[T]) -> LoadResult[T]:
        file_path = self.sample_dir / filename
        if not file_path.exists():
            msg = f"File mẫu không tồn tại: {file_path}"
            logger.warning(msg)
            return LoadResult(errors=[msg])

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    msg = f"File mẫu rỗng: {file_path}"
                    logger.warning(msg)
                    return LoadResult(errors=[msg])
                raw_data = json.loads(content)
        except json.JSONDecodeError as e:
            msg = f"Lỗi cú pháp JSON trong file {filename}: {e}"
            logger.error(msg)
            return LoadResult(errors=[msg])
        except Exception as e:
            msg = f"Lỗi đọc file {filename}: {e}"
            logger.error(msg)
            return LoadResult(errors=[msg])

        if not isinstance(raw_data, list):
            msg = f"Nội dung file {filename} không phải danh sách mảng (JSON list)"
            logger.warning(msg)
            return LoadResult(errors=[msg])

        result = LoadResult[T](total_records=len(raw_data))

        for idx, item in enumerate(raw_data):
            if not isinstance(item, dict):
                err = f"{filename}: record {idx} không phải kiểu JSON object (dict)"
                logger.warning(err)
                result.skipped += 1
                result.errors.append(err)
                continue
            try:
                model_instance = model_cls.model_validate(item)
                result.items.append(model_instance)
                result.loaded += 1
            except ValidationError as e:
                err = f"{filename}: record {idx} lỗi validation: {e.errors()}"
                logger.warning(err)
                result.skipped += 1
                result.errors.append(err)
                continue

        return result

    def load_projects_result(self) -> LoadResult[Project]:
        return self._load_and_validate("projects_sample.json", Project)

    def load_tasks_result(self) -> LoadResult[Task]:
        return self._load_and_validate("tasks_sample.json", Task)

    def load_field_logs_result(self) -> LoadResult[FieldLog]:
        return self._load_and_validate("field_logs_sample.json", FieldLog)

    def load_issues_result(self) -> LoadResult[Issue]:
        return self._load_and_validate("issues_sample.json", Issue)

    def load_document_tracks_result(self) -> LoadResult[DocumentTrack]:
        return self._load_and_validate("document_tracks_sample.json", DocumentTrack)

    # Convenience methods returning item lists
    def load_projects(self) -> List[Project]:
        return self.load_projects_result().items

    def load_tasks(self) -> List[Task]:
        return self.load_tasks_result().items

    def load_field_logs(self) -> List[FieldLog]:
        return self.load_field_logs_result().items

    def load_issues(self) -> List[Issue]:
        return self.load_issues_result().items

    def load_document_tracks(self) -> List[DocumentTrack]:
        return self.load_document_tracks_result().items

    def load_all_summary(self) -> Dict[str, Any]:
        """Đọc và trả về số lượng các bản ghi và thống kê lỗi."""
        pr = self.load_projects_result()
        tk = self.load_tasks_result()
        fl = self.load_field_logs_result()
        iss = self.load_issues_result()
        doc = self.load_document_tracks_result()

        all_errors = pr.errors + tk.errors + fl.errors + iss.errors + doc.errors

        return {
            "projects": {"total": pr.total_records, "loaded": pr.loaded, "skipped": pr.skipped},
            "tasks": {"total": tk.total_records, "loaded": tk.loaded, "skipped": tk.skipped},
            "field_logs": {"total": fl.total_records, "loaded": fl.loaded, "skipped": fl.skipped},
            "issues": {"total": iss.total_records, "loaded": iss.loaded, "skipped": iss.skipped},
            "document_tracks": {"total": doc.total_records, "loaded": doc.loaded, "skipped": doc.skipped},
            "total_loaded": pr.loaded + tk.loaded + fl.loaded + iss.loaded + doc.loaded,
            "total_skipped": pr.skipped + tk.skipped + fl.skipped + iss.skipped + doc.skipped,
            "errors": all_errors,
        }
