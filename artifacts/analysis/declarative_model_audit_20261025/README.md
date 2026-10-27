# 声明模型源码审计

2026-10-25。说明见 [DECLARATIVE_MODEL_AUDIT.md](../../../docs/DECLARATIVE_MODEL_AUDIT.md)。
所有文件是审计记录，不是新 IR，不是 whole-model PASS 收据。

在工作树根运行 `python3 artifacts/analysis/declarative_model_audit_20261025/audit.py` 可重建 JSON。
只解析 SCAR 源码与 hash 六份指定文档，不 import SCAR、不执行目标、不读取 raw 或旧 artifact。
`audit.json` 为人工读过生产/codec/validation 正文后的映射；其原类字段由 AST 目录自动核对。
`typed_records.json` 包含原三个目录的全部 dataclass（包括查询结果和兼容记录），不是执行节点计数。
`constructor_sites.json` 只是定向语法调用点，不能凭没有直接调用断言没有间接 decoder/producer。

状态分别为 AUTO_PARTIAL（有自动 producer、未整次闭合）、SUPPLIED（声明/校验可用）、
DESIGN_ONLY（统一 scope/验收 ledger 尚无完整实现）。第一阶段全自动恢复和必需关系 OPEN=0
仍为当前合同；旧文档中的后移安排不适用。
