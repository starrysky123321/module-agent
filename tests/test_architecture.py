import ast
from pathlib import Path


SOURCE_ROOT = Path(__file__).parents[1] / "src" / "module_agent"
BUSINESS_MODULES = {
    "code",
    "literature",
    "supervision",
    "validation",
    "venue_catalog",
    "workflow",
}


def _python_files(directory: Path) -> list[Path]:
    return sorted(directory.rglob("*.py"))


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)

    return imports


def test_domain_does_not_depend_on_application_or_adapters() -> None:
    violations: list[str] = []

    for module_name in BUSINESS_MODULES:
        domain = SOURCE_ROOT / module_name / "domain"
        if not domain.exists():
            continue

        forbidden = (
            f"module_agent.{module_name}.application",
            f"module_agent.{module_name}.adapters",
        )
        for path in _python_files(domain):
            for imported in _imports(path):
                if imported.startswith(forbidden):
                    violations.append(f"{path}: {imported}")

    assert violations == []


def test_application_does_not_depend_on_its_adapters() -> None:
    violations: list[str] = []

    for module_name in BUSINESS_MODULES:
        application = SOURCE_ROOT / module_name / "application"
        if not application.exists():
            continue

        forbidden = f"module_agent.{module_name}.adapters"
        for path in _python_files(application):
            for imported in _imports(path):
                if imported.startswith(forbidden):
                    violations.append(f"{path}: {imported}")

    assert violations == []


def test_shared_does_not_depend_on_business_modules() -> None:
    forbidden = tuple(
        f"module_agent.{module_name}"
        for module_name in BUSINESS_MODULES
    )
    violations: list[str] = []

    for path in _python_files(SOURCE_ROOT / "shared"):
        for imported in _imports(path):
            if imported.startswith(forbidden):
                violations.append(f"{path}: {imported}")

    assert violations == []
