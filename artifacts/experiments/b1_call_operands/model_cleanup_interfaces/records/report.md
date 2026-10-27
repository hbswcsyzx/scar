# C1 records：有限实施报告

2026-10-16。依据冻结 `docs/M1_CLEANUP_INTERFACES.md`。
本子任务仅编辑 `scar/ir/program/cleanup.py` 和
`tests/unit/test_program_cleanup_records.py`；没有提交、安装、运行 workload 或修改 LeWM。

## Implemented

- 八个 frozen/slots 记录：HandledContextDomain、CleanupInterface、CleanupEnter、
  CleanupResume、CleanupReplace、HandledContextRead、CleanupRouteSuccessor、
  CleanupRouteTerminator；字段及顺序按冻结规格。
- exact ID/record/tuple 类型，嵌套 FrameRules、ControlEdgeReference、route successor
  递归重检；沿用固定 UNKNOWN 适用条件，不增加可写授权字段。
- route 参数仅 UseID，禁止 PendingPayload；successors 非空且 port 唯一，允许多
  case 共用 block。kind 局部导入，condition/exit/values 不序列化成额外规范字段。
- 端点不存在、scope sibling、same-token freshness、重复 Use ownership 等图级关系
  不由构造器猜测；不另存 state、actuals、producer 或 payload 内容。

## Verified（仅构造层）

首轮唯一测试命令：

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m pytest -q tests/unit/test_program_cleanup_records.py
```

实际结果：**28 passed in 0.31s；exit 0**。首轮日志为
[pytest.initial.log](pytest.initial.log)，没有失败、修改后重跑或套件扩展。
测试覆盖严格 ID 命名空间/子类拒绝、固定 rules 篡改、edge bool/负下标篡改、route
无投影/端口重复拒绝、嵌套重检、共享目标、有序 Use、通用 record_codec 往返与额外
字段拒绝；不是以手工图证明语言执行正确。

本轮文件 SHA256：

```text
79b5888885bf8c4ad50df77e8f6dc7ffff4e5aa8956aca9010a98a055cbd372c  scar/ir/program/cleanup.py
24a478ac88ef37aca41d74ee358e2fc5bff90ac865a88db7a7e0a6378a9c7914  tests/unit/test_program_cleanup_records.py
```

## 未实施/未验收

本子任务不含 graph/model/wire/公开入口集成、全域后态、操作点 LIFO、全 CFG 路由、
activation-local must-forward/must-fresh、源/runtime 对应或真实 cleanup adapter。
没有运行 full、LeWM、GPU、capture 或性能测量；28 PASS 不表示 C1 全门、M1/M2
或完整程序建模已完成，也不授权任何变换。
