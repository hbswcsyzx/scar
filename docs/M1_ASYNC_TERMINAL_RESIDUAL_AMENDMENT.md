# 原 F18：实际反例驱动的最小补充

2026-10-20。保留原冻结计划及原十六族/113 构造/196 字段，不扩大 F19 或 backend。
首测 38 项 20 败；修订后 40 项 2 败、38 通过，均899源稳定。修订后实际指纹
`4b6dd7e5d54b14bec907d2c32b4cfcd1f3df5f572d899a67f393512ad8f7558e`。
原失败、源码和 JUnit 不改写；本补充先于对应产品修订。

## 准确阻断

1. 原 `protocol_validation.py` 把 later primitive 的 own RAISE 仍要求复制早先
   BodyRAISE 包。dynamic host 已修优先级，但合法原图在静态层先被拒。
   使用既有 source_inventory/source_routes 的原边选择，识别自己的 RAISE
   completion slot，逐路线检查当前 packet→host；不能因同型或可达就批准。
   后续 helper 新包不能借旧 body 包替代，normal 路线仍保原 body/adapter 义务。
2. `admission.py` 的只读形状检查在 `ctx.port()` 因共享预算返回 None 后解引用。
   缺结果只保原 budget gap，不冒 bool/owner 证明；原节点/结果/消费者库存不删。
3. 独立审查提出 `type_comments=True` 可能拒绝普通 compiler 接受的源码；新
   `type-comment-probe.json` 已实际确认 `pass # type: int` 的三种模式不同。
   可选 metadata 解析不能伪装 Python 程序非法。普通 AST fallback 必须显式
   标明 frontend AST namespace 不对应，不借相同字节位置/atom 名称批准 links。

辅助 residual 探针两次因试图在已被拒的图上取得公开/prepared index 而失败；
这两份原脚本和日志保留，不作为 completion walker 已运行的证据。
独立 type-comment 探针已成功，目标执行0；不是产品测试或 source/runtime proof。

## 授权与验收

root 旧生产文件范围由原两份扩大至四份：`protocol_async.py`、
`execution/resumable_sessions.py`、`program/protocol_validation.py`、
`program/admission.py`。仍只改已有数据/控制/完成连接，没有新类型、profile、
codec 或 schema；Program26/Execution8 保持。root 原NEW inventory unit追加
准确 helper 正反；B只修原两NEW源编译文件和有限反例。A/C仍冻结。

原旧测试/fixture全部字节不变，原2058 testcase身份精确保留；全部作者再次冻结
后root串行复测有限新组，再跑一次最终affected selection。先审具体反例再修，
不把缺预算/未知来源变通过，不把手供模型当自动恢复，F19及剩余原门仍开放。
