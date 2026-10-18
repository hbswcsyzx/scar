# C2D连接合同第二稿审查证据

2026-10-18；基线 `499d708f9092a8bf35915e8db9a004631a223d7b`。
本批是 D1 连接字段/实施范围的架构审查，**没有新增产品driver、detector或backend**。
完整 D0/D2/D3、M0–M2 和自动 LeWM 建图未关闭，无新的加速比。

## 证据及决定

- 三份原提案分别审查 core 连接、gate/session、outcome/lifecycle；原件不改写。
  root-request-phase-resolution 与 core-resolution 保存之后的撤回/修正。
- 采用 final gate INVOKE→私有单操作 BodyDrive，不增加可传递 permit；用现
  CompletionResult 定义准入后态，原 owner/request 经独立 Uses 精确转发。
- 不强制所有实现有独立 RequestGate 或 U/A 历史状态机；真正早期步骤保留真实
  helper/state。final gate 检查当前关联/资格。Start 不强制唯一 local Create。
- 每条 Drive successor.source 指向本次 first frontier 的确切 operation；有限
  出口不表示 must-return，空 frontier 不捏造结果。原body规范Uses仍为唯一来源。
- D1修正复审和D2未冻结的实质问题均保留在各 root-*-contract 报告中。
  `reviewed-contract.md`保存获复核的连接合同内容，不是driver实现文件。

## 实际运行范围

`review/corridor-probe.py`使用现有core的两个普通opaque INVOKE研究接线，第二个
**不是BodyDrive**。修正后六个检查：合法后态/原owner、旧wire往返、旧state拒绝、
新产生owner需要专用规则、interposition需要专用规则、一个引用的独立Use occurrence。

初稿在第五个检查构造时错误使用不存在的Behavior.OPAQUE，exit1；这是探针错误，
不是core误判。原脚本、命令/hash和traceback保留。改成已有Behavior.CONTROL后
exit0，六项设计检查通过，命令/hash/原始stdout及JSON分别保留。没有新pytest、
语言行为、GPU、LeWM或full测试；不把此前3,549项旧回归充作本批新功能验证。

`source-snapshot.json`与此前冻结full指纹及26份fixture逐项相同。仅文档/有界证据
变化，不重复旧full验收。`acceptance.json`精确区分D1设计通过和产品/D2未完成。

本批最终只读核验：

```bash
conda activate lewm
python artifacts/experiments/b1_call_operands/model_driver_contract_v2/check_evidence.py
```

该脚本校验归档哈希/范围，不运行probe、pytest、LeWM或GPU。
下一批按 `docs/M1_DRIVER_IMPLEMENTATION.md` 实施完整的声明连接路径并单独自验收。
