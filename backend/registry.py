from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class ProjectManifest:
    id: str
    name: str
    description: str
    href: str
    accent: str
    api_prefix: str
    status: str = "ready"


PROJECTS = (
    ProjectManifest(
        id="modal-drive",
        name="Modal Drive",
        description="基于 Modal Volume 的分片云端文件管理。",
        href="/projects/drive",
        accent="yellow",
        api_prefix="/api/drive",
    ),
    ProjectManifest(
        id="deepl-router",
        name="DeepRouter",
        description="支持健康检查、优先级回退与加权轮询的翻译路由。",
        href="/projects/router",
        accent="purple",
        api_prefix="/api/router",
    ),
    ProjectManifest(
        id="ai-model-checker",
        name="AI Model Checker",
        description="发现并测试 OpenAI 兼容模型与流式对话。",
        href="/projects/models",
        accent="green",
        api_prefix="/api/models",
    ),
)


def public_projects() -> list[dict]:
    return [asdict(project) for project in PROJECTS]
