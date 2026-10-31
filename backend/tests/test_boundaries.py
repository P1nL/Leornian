import ast
from pathlib import Path


def test_business_modules_only_import_other_modules_public_contracts():
    modules = Path(__file__).parents[1] / "src" / "leornian" / "modules"
    violations = []
    for source in modules.rglob("*.py"):
        owner = source.relative_to(modules).parts[0]
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            else:
                continue
            for name in names:
                parts = name.split(".")
                if parts[:2] == ["leornian", "modules"] and len(parts) >= 3:
                    if parts[2] != owner and (len(parts) < 4 or parts[3] != "contracts"):
                        violations.append(f"{source.name}:{node.lineno}: {name}")
        # SQL stays with its data owner as well as Python imports.
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                text = node.value.strip().upper()
                if text.startswith(("SELECT ", "INSERT ", "UPDATE ", "DELETE ")):
                    for other in (
                        "identity",
                        "learning",
                        "tutor",
                        "runtime",
                        "knowledge",
                        "item_bank",
                        "assessment",
                        "execution",
                    ):
                        if other != owner:
                            assert other + "." not in node.value, f"Cross-owner SQL in {source}"
    assert not violations, "\n".join(violations)
