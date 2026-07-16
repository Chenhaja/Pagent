from pathlib import Path

from app.core.config import Settings
from app.services.case_service import CaseService


def test_case_service_creates_case_metadata_with_relative_workspace_path(tmp_path: Path) -> None:
    """案件服务应创建案件元数据并只返回相对 workspace 路径。"""
    service = CaseService(settings=Settings(draft_workspace_dir=str(tmp_path)))

    case = service.create_case()

    assert case["case_id"]
    assert case["workspace_id"]
    assert case["workspace_path"] == f".draft_workspace/tmp_{case['workspace_id']}"
    assert Path(case["workspace_path"]).is_absolute() is False
    assert (tmp_path / "cases" / f"{case['case_id']}.json").exists()
    assert (tmp_path / f"tmp_{case['workspace_id']}").is_dir()


def test_case_service_reads_existing_case_metadata(tmp_path: Path) -> None:
    """案件服务应按 case_id 读取已创建的案件元数据。"""
    service = CaseService(settings=Settings(draft_workspace_dir=str(tmp_path)))
    created = service.create_case()

    loaded = service.get_case(created["case_id"])

    assert loaded == created


def test_case_service_rejects_unknown_case(tmp_path: Path) -> None:
    """案件服务读取不存在案件时应返回 None。"""
    service = CaseService(settings=Settings(draft_workspace_dir=str(tmp_path)))

    assert service.get_case("case_missing") is None
