# C：module Try 传播载荷与 except-as 清理交付

原构建窗口保留 **exit1**；独立只读 postflight **exit0**。同一 C-SP8 图正常读回及 source/C0/C1 校验通过，模块仍为精确 prefix + REQUIRED suffix，整体 OPEN。

| 窗口 | Root 实际终态 | 范围 |
|---|---|---|
| candidate01 / session6695 | exit1，outer 22.157462589s | 原图已写、普通完整 reader 已越过；末次 runtime freeze 缺 uuid.py / _uuid.so，原失败不改 |
| postflight01 / session59038 | exit0，outer 14.691772119s / worker 14.427582454s | 仅同一保留图正常 reader、独立 source/C0/C1 与最终源码/输入/runtime 检查；lower0 |

postflight readonly CodeWitness 为 1 load / 1 match / 0 compile；target executable compile / exec / source prepare 均0，AST分析8次、symtable0，不能称所有compile均0。实际输入4,133,867B（stored458,871 + decoded3,674,996，含重复读），RSS149,188KiB。输入32MB、单record4MB、输出16MB、worker180s/outer240s均未提高；补 preload uuid/_uuid 后146个 runtime 条目完成末核。

原窗口 failure receipt 另保存实际输入6,154,780B、AST18、readonly1/1/0与prepare/target0。原窗口未落盘的 construction 汇总及最终 runtime 资格保持 **OPEN_NOT_RECONSTRUCTED**，本次读回不重建过去测量。原 B 消费仅作为原 candidate01 控制流已越过的观察，不把其旧门改成PASS，也不在postflight重跑。

## 当前静态图与准确剩余范围

- 同源586B root，原 source census 保持95 atoms / 92 semantic definitions / 45 CFG nodes / 56 edges。
- 当前图354 ops、622 values、2 Regions；9个顶层 statement 接口、12条 expansion records。新增通用单handler Try/except-as 拓扑对应原11–14行，原循环仍是1条循环接口，不展开迭代。
- core C0/C1 有 FRAME1 / BLOCK2 / CLEANUP1，control ports47、pending completions47、exception packets46、exception matcher1；cleanup interface1 / Enter1 / Replace7 / Resume1。namespace StateAddress refinements28，StoredValueWrite0，不能把正常 STORE 尝试当已写内容。
- 精确 remaining 为原15行 Assert 与16–18行 Expr，两条均 REQUIRED；不是整个模块完成。静态数量来自 postflight normal summary，以及对同一已验SHA artifact的有界JSON记录清点，非原construction活动或动态执行计数。

C profile使用每次错误边的(exceptionRef, thisPropagationTracebackRef, W)协议端口，保留原packet的 Resume/RERAISE；不是读取 exception.__traceback__，也没有动态 traceback 观测。通用handler type lookup/match、绑定失败不清名、正常路径先restore再清名、异常路径先清名再restore均由现source+C0/C1 validator检查。frame-exit在PendingDispatch之后的普通block landing使用packet，出口shim保持现core合同，不新增pending权威。

## 版本、限制与保留

仅六生产文件；显式非默认 `STRUCTURED_MAPPING_PROPAGATION_314_V1` + `PROPAGATION_REF_PAIR_314_V1`，保持SP8/core29、旧RAW profile、source1–7与function默认合同。core模型/codec/cleanup文件不改；函数既有 failure payload 默认仍单ref。

namespace/custom mapping内容、别名、import/callee内部、实际Frame/activation、传播端口runtime适用性、callback/retention effects仍OPEN；不授优化、运行或完整建模资格。source858/runtime843历史指针未变，未ADD、未bind、未publish、未新episode。

压缩图312,932B已纳入本次显式保留：stored SHA `c4749c043de831cd3c4ab570e90d442db3c9e78443511bb93b183e2374a090aa`；decoded3,527,430B SHA `dbd78862ad2080f41e0126eea1144c96eef911c910dae6178edaca9c16740677`。原freeze/result/failure/progress/time/runner及新postflight原件均保留，大的只读输入不复制。B基线六源已由Git `8078ffdecff2734c5baeac3d6bdf7a6c436c0b55` 精确复用，见BASELINE_REUSE.json。

交付边界见 STAGE_PATHS.txt / STAGE_MANIFEST.json / DELIVERY_INVENTORY.json；原计划与固定CPython主源依据见 `artifacts/analysis/module_try_propagation_c_plan_20261026/`。后续main兼容消费由Root另行执行，本报告不代其结论。
