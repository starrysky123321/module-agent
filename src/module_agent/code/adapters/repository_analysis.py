import asyncio
import json
import re
import tomllib
from pathlib import Path
from typing import Any

from module_agent.code.domain.artifact import RepositoryAnalysis
from module_agent.code.domain.request import CodePaperInput


DEPENDENCY_FILE_NAMES = {
    "environment.yml",
    "environment.yaml",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "setup.cfg",
    "setup.py",
}
ENTRYPOINT_NAMES = {
    "app.py",
    "cli.py",
    "demo.py",
    "evaluate.py",
    "inference.py",
    "main.py",
    "predict.py",
    "run.py",
    "train.py",
}
TEXT_SUFFIXES = {
    ".cfg",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".rst",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}")


class LocalRepositoryAnalyzer:
    """在不执行仓库代码的前提下分析依赖、入口和资源要求。"""

    def __init__(
        self,
        *,
        max_files: int = 5000,
        max_file_bytes: int = 1_000_000,
    ) -> None:
        if max_files <= 0 or max_file_bytes <= 0:
            raise ValueError("Repository analysis limits must be positive")
        self.max_files = max_files
        self.max_file_bytes = max_file_bytes

    async def analyze(
        self,
        repository_path: Path,
        paper: CodePaperInput,
        *,
        code_requirements: str | None = None,
    ) -> RepositoryAnalysis:
        """在线程中执行有界静态文件扫描。"""
        return await asyncio.to_thread(
            self._analyze,
            repository_path,
            paper,
            code_requirements,
        )

    def _analyze(
        self,
        repository_path: Path,
        paper: CodePaperInput,
        code_requirements: str | None,
    ) -> RepositoryAnalysis:
        root = repository_path.resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"Repository path does not exist: {root}")

        files: list[tuple[str, str]] = []
        warnings: list[str] = []
        scanned = 0
        for path in sorted(root.rglob("*")):
            if scanned >= self.max_files:
                warnings.append(
                    f"Repository scan stopped after {self.max_files} files"
                )
                break
            if path.is_symlink() or not path.is_file() or ".git" in path.parts:
                continue
            scanned += 1
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size > self.max_file_bytes:
                continue
            if (
                path.suffix.casefold() not in TEXT_SUFFIXES
                and path.name.casefold() not in DEPENDENCY_FILE_NAMES
            ):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            files.append((path.relative_to(root).as_posix(), text))

        dependency_files = sorted(
            path
            for path, _ in files
            if _is_dependency_file(path)
        )
        dependencies = _extract_dependencies(files)
        entrypoints = sorted(
            path
            for path, text in files
            if _is_entrypoint(path, text)
        )[:30]

        search_text = " ".join(
            value
            for value in (
                paper.title,
                code_requirements,
                paper.method_profile.module_type
                if paper.method_profile is not None
                else None,
            )
            if value
        )
        keywords = {
            token.casefold()
            for token in TOKEN_PATTERN.findall(search_text)
            if len(token) >= 4
        }
        module_candidates = _matching_paths(files, keywords)
        requirement_keywords = {
            token.casefold()
            for token in TOKEN_PATTERN.findall(code_requirements or "")
            if len(token) >= 4
        }
        requirement_matches = _matching_paths(files, requirement_keywords)

        return RepositoryAnalysis(
            dependency_files=dependency_files,
            dependencies=dependencies,
            entrypoints=entrypoints,
            module_candidates=module_candidates,
            dataset_references=_resource_references(files, "dataset"),
            weight_references=_resource_references(files, "weight"),
            requirement_matches=requirement_matches,
            warnings=warnings,
        )


def _is_dependency_file(path: str) -> bool:
    """判断文件名是否属于常见依赖清单。"""
    name = Path(path).name.casefold()
    return name in DEPENDENCY_FILE_NAMES or name.startswith("requirements")


def _extract_dependencies(files: list[tuple[str, str]]) -> list[str]:
    """从常见清单格式提取依赖名称，不执行任何配置代码。"""
    result: set[str] = set()
    for path, text in files:
        name = Path(path).name.casefold()
        if name.startswith("requirements"):
            for line in text.splitlines():
                value = line.split("#", 1)[0].strip()
                if value and not value.startswith(("-", "http://", "https://")):
                    result.add(
                        re.split(
                            r"[<>=!~;\[]",
                            value,
                            maxsplit=1,
                        )[0].strip()
                    )
        elif name == "pyproject.toml":
            try:
                payload = tomllib.loads(text)
            except (tomllib.TOMLDecodeError, ValueError):
                continue
            project = payload.get("project")
            if isinstance(project, dict):
                values = project.get("dependencies", [])
                if isinstance(values, list):
                    for value in values:
                        if isinstance(value, str):
                            result.add(
                                re.split(
                                    r"[<>=!~;\[]",
                                    value,
                                    maxsplit=1,
                                )[0].strip()
                            )
            poetry = payload.get("tool", {}).get("poetry", {})
            if isinstance(poetry, dict):
                values = poetry.get("dependencies", {})
                if isinstance(values, dict):
                    result.update(str(key) for key in values if key != "python")
        elif name == "package.json":
            try:
                payload = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(payload, dict):
                for section in ("dependencies", "devDependencies"):
                    values = payload.get(section)
                    if isinstance(values, dict):
                        result.update(str(key) for key in values)
    return sorted(value for value in result if value)[:200]


def _is_entrypoint(path: str, text: str) -> bool:
    """识别常见命令入口和含 Python main guard 的文件。"""
    name = Path(path).name.casefold()
    return name in ENTRYPOINT_NAMES or "if __name__ ==" in text


def _matching_paths(
    files: list[tuple[str, str]],
    keywords: set[str],
) -> list[str]:
    """返回路径或内容包含用户关键词的候选文件。"""
    if not keywords:
        return []
    matches: list[tuple[int, str]] = []
    for path, text in files:
        haystack = f"{path}\n{text[:100_000]}".casefold()
        score = sum(keyword in haystack for keyword in keywords)
        if score:
            matches.append((score, path))
    return [path for _, path in sorted(matches, key=lambda item: (-item[0], item[1]))[:30]]


def _resource_references(
    files: list[tuple[str, str]],
    kind: str,
) -> list[str]:
    """从说明和配置中提取数据集或模型权重相关的短文本证据。"""
    terms = (
        ("dataset", "data set", "dataloader", "download data")
        if kind == "dataset"
        else ("checkpoint", "pretrained", "model weight", ".pth", ".ckpt")
    )
    references: list[str] = []
    for path, text in files:
        if Path(path).suffix.casefold() not in {".md", ".rst", ".txt", ".yaml", ".yml", ".json", ".toml"}:
            continue
        for line in text.splitlines():
            normalized = line.strip()
            folded = normalized.casefold()
            if normalized and any(term in folded for term in terms):
                references.append(f"{path}: {normalized[:240]}")
                if len(references) >= 20:
                    return references
    return references
