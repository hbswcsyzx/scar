# C0 frame 生命周期：有限前端验收

日期：2026-10-15。状态：**F0–F3 有限范围 Verified；F4 外部来源复验运行中**。
完整 N2.call-edges E4、完整程序依赖闭包及优化合法性仍未通过。

## 冻结依据

- 实现提交：`5fa3c17`；默认版本断言迁移：`72aaf54a74fbc923f5c92329817347bf6cfecc53`。
- 源码/测试/gate指纹：`c8de5831ed8afb1378ba41fd7b2373de599fd818520d03970b1ec04665666d7c`。
- 映射验收：**863 tests PASS / 143.949s**，35项criterion逐项通过。
- 全仓回归：**1,898 tests PASS / 209.470s**，零失败、错误或skip；
  三项已知warning见原始log（finally-return反例、多线程fork、Torch量化）。
- 两次冻结运行期间源码未变；合入主分支后再次核对相同指纹。
- 原始证据：`artifacts/reports/gates/n2-frame-verified.json`及`.md`，
  `n2-frame-full.json`、`.xml`、`.log`。

## 自动实现，而非手工图

输入原始`.py`、入口/项目范围和预算。源码读取不执行目标；从源码自动产生
BOUND_FRAME_V1的Operation/Value/StateLocation/Region和FrameModel对应。
未使用业务函数名单、人工纯度标记、手工参数类型或LeWM图修补。

ENTER接入全部形参持有；BIND包含首次、覆盖、自绑定；Expr临时持有在原点
DISCARD；正常/异常EXIT保留已求值payload与求值后world，最终完成使用自己的
UseID读取原ValueID。仅声明真实连接的normal/raise出口。领先docstring属于
定义元数据。未支持的生命周期/控制边界保留明确UNSUPPORTED。

`model-program`默认v2/root-only；`inventory-program`默认v5、自动调度多个body。
`query-frame-refs`在逐前驱返回引用与未知效果之间保持边界；opaque结果不因输入
相同而被当作alias。详见[N2_FRAME_IMPLEMENTATION.md](N2_FRAME_IMPLEMENTATION.md)。

## 验收覆盖

| 门 | 实际证据 |
| --- | --- |
| F0 | strict typed records、固定UNKNOWN规则、slot/source/context、core状态/完成/payload篡改；独立审查修复BIND/DISCARD误锚FunctionDef及async整数元数据 |
| F1 | 原始源码return formal/alias/new local、分支逐路径、None/fallthrough；公共命令引用查询及预算边界 |
| F2 | 全部formal/unused、branch-only local、首次/覆盖、自绑定、DISCARD时点、异常后态及一次unwind；CPython实际运行析构改内容、unraisable、frame/traceback保留 |
| F3 | 真实历史包分别生成inventory v1/v2/v3/v4与完整v4 call report后严格重放；新v2/v5字段、世界状态、source/profile、独立budget、回滚、context、重复JSON和原子写入反例 |

结构与源码完整性分开验收：同时删除BIND操作及对应并缝回world，或同时改EXIT
和RETURN payload，core/frame结构可一致；原始源码重建仍必须拒绝。
F0只证明formal集合覆盖；canonical参数次序由独立signature及source replay核对。

## 发现过的真实问题与处理

1. 新return不再invoke后，无异常路径的body仍声明raise port：修为仅声明已绑定出口。
2. v5直接RETURN与v4 opaque return的source-use形态不同，造成5项旧调用查询回归：
   按profile通过FrameModel读取真实RETURN payload，旧测试原断言恢复通过。
3. 新查询最初复用宽松json.load：改为有解压预算、拒绝重复字段/非有限数的严格解码；
   输出超限原子保留已有文件。独立审计再次复现确认拒绝。
4. 第一冻结门861 PASS/2 FAIL为旧默认v4与“每个body必须invoke”的断言；保留
   `n2-frame-attempt1.json/.md`，迁移断言为v5及frame未知效果，算术/call仍必须invoke。
   重新冻结后863项全部通过，未删除、跳过失败测试。

## 仍未满足与下一步

FrameRules.condition_status仍UNKNOWN，effects incomplete，可能不完成，释放不保证。
引用一致不证明内容不变、无效果或允许缓存。actual→formal、receiver、default/cell
来源仍未证；C0不恢复已撤销的错误参数边。

F4正在从原LeWM入口与已归档真实trace、相同预算重建/重放v5，目录：
`artifacts/experiments/n2_frame_source_f4/real/`。未完成前不填写覆盖变化或外部通过。
此前真实calls-only公共重放REPLAYED的84,319次入口/出口是独立证据，不能替代F4。

完成F4后，依[调用组合计划](N2_CALL_COMPOSITION_PLAN.md)推进实际callable/环境
与逐调用绑定/完成/state；接入新运行code见证的需求展开，再闭合循环、细状态及
provenance，最后从观察根生成化简指导。预算调度OBSERVED_CODE仅是运行来源候选
优先级；缺失版本或未核验code不会因此成为已证明源码执行。

**没有新backend、LeWM源码修改、TRANSFORM、clean A/B或已验证加速比。**
