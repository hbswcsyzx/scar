已接通正常 source 构造与 call-link factory，未接 model_run 自动选择。

```python
from scar.analysis.program_lowering import prepare_captured_source
from scar.analysis.call_edges import link_calls

prepared = prepare_captured_source(owner, original_captured_code,
    project_root=original_namespace_root, root_is_package=explicit_original_policy)
# prepared 是原 PreparedSource，含原 SG/semantics/CFG/AST/symtable，不能作 loaded proof。
report = link_calls(trace, original_project_root,
    captured_source_owner=owner,
    captured_source_root_is_package=explicit_original_policy)
# 普通 report reader 可接同名 owner/policy kwargs，正常重放，不从 JSON 恢复 owner。
```

普通 `_link_call_model` 也透传同名 kwargs；同 fresh normal frame scan/entries/exits 可照原 in-process 接口复用。本轮真实门走该普通 factory，保持原177条分母。`_Sources.context(filename, captured=...)` 经 owner→`prepare_captured_source`→纯 text frontend→原 `_source_witness_projection`，`_Sources.code` 仍实际完整 descriptor 匹配才给 VERIFIED；`source_origins[filename]` 仅保原不可变 SourceFact/text 来源，不是第二套程序图。

`prepare_source_text` 是静态构造入口，不接受/生成 loaded applicability 布尔。`prepare_captured_source` 只收正常 CapturedSourceOwner+原 CapturedCode，核 snapshot/version/encoding 并在前后校 owner；缺原字节返回 SOURCE_BOUNDARY/INCOMPLETE，无 live fallback。`root_is_package` 是显式静态 namespace 输入，不是 import/ModuleObject 证明；没捕获 namespace policy 时保 CAPTURED_NAMESPACE_POLICY_UNAVAILABLE，不能据缺失 `__init__` 行猜 False。

旧 prepare_source/link_calls 默认 live 路径与 report wire 保留。新 archive owner 与旧 live workspace 或 bound SourceBodyAccess 混用，目前明确拒绝，防止旁路原资格；dependency root 的选择仍须用原 admission 规则，不能把外部库改入 project root。本轮没有改 dependency_sources，也没有做完整 dependency admission。V2 owner 适配由 Root 保留，本四源不回滚它。

后继自动入口两处：

1. `call_seeds.py:_read_call_source_seeds` 的 `_Sources(...)` 接正常 owner/policy；`model_run.py:seeds_stage`（原604行）识别闭合 `captured_sources`，使用同 scan/元数据。原614后 `paths` 的 live is_file/resolve 过滤也须换成原 snapshot/member 资格；namespace policy 缺失则发布缺口。
2. `model_run.py:inventory_stage`（原629行）尚进 live discovery/expansion；后继把正常源构造接 `prepare_captured_source`，witness_stage（原686行）在 resolve 前 `admit_captured_source`。依赖 `_Archives.source`/workspace 的 live 读取仍需显式 archive adapter，不能把本次 call-link 成功说成全 model-run 已自动化。
