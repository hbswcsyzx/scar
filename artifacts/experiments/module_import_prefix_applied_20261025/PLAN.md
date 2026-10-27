# 模块 import 前缀接入主树

仅接入独立 postflight 已通过的四源，不重新 lower。原 candidate02 因报告变量遮蔽
exit1；原错误和丢失测量保持，不改为 PASS。新 postflight 的普通结构/源码/只读编译
根见证通过，证明原 SP7 的首句接口、状态尝试和准确剩余 slice 可以独立读回。

接入先核主树与 9308d91e 基线四源逐字相等，应用冻结四源。主树只消费原 SP7、
旧 SP6 及旧 SP5，正常 reader 保留全部图和来源；不执行模块、import 或 lower。
外部60s，直接 stored+decoded 32MB，组合/见证 API 各保原限制，累计 I/O 单列 OPEN。
验证成功仍是 1 个语句接口/4 Regions/19 ops，10句及 importer 内部继续 REQUIRED。
