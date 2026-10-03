"""New boundary kinds must not disappear at an existing value-path consumer."""
import pytest

from scar.analysis.import_values_v2 import (
    ImportConditionStatus, ImportValueStatus, resolve_import_values,
)
from scar.analysis.source_semantics_v2 import extract_source_semantics
from scar.ir.frontend_v2 import build_semantic
from scar.ir.semantics_v2 import Opcode


@pytest.mark.parametrize("comparison", ["unknown == other", "unknown is other is third"])
def test_module_export_after_user_comparison_remains_blocked(tmp_path, comparison):
    package = tmp_path / "sample"
    package.mkdir()
    (package / "__init__.py").write_text(f"TABLE = ((2, 7),)\n{comparison}\n")
    source = tmp_path / "program.py"
    source.write_text("import sample as module\nanswer = module.TABLE[0][1]\n")
    semantic = build_semantic(source, project_root=tmp_path).graph
    overlay = extract_source_semantics(semantic)
    report = resolve_import_values(semantic, overlay)
    target = max((operation for operation in overlay.operations.values()
                  if operation.opcode is Opcode.INDEX and operation.source.path == str(source)),
                 key=lambda operation: operation.source.end_column)
    fact = report.facts[target.result]
    assert fact.status in {ImportValueStatus.BLOCKED, ImportValueStatus.UNRESOLVED}
    assert target.result not in report.guidance
    assert report.validate()["valid"]
    assert any(condition.status is ImportConditionStatus.SOURCE_BLOCKER
               for fact in report.facts.values() for condition in fact.conditions)
