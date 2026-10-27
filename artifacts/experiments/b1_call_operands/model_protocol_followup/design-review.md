# P4 后续设计审查

起点：`7dd8c54b8d8cfdb3454b9f3b671f3412d1a914f0`。
计划：`docs/M1_PROTOCOL_FOLLOWUP_PLAN.md`，SHA256
`44437087abfe3fa1a7b074ca973c06a0f863eb0c4fc9073ef26f8881de412f78`。
状态：**PASS_WITH_SCOPE_DESIGN**；此状态不是实现、组件、P4 或 M0–M2 验收。
本次审查为三位 subagent 与 root 的只读源码推导，没有运行 native 探针或测试。

## 独立审查与决定

1. `cleanup_forward_review`：四个闭合 lookup 规则可复用 ProtocolCall 与原
   N/R/result/Use，不需新图。iterator 是查找的 receiver，bound method 是调用的
   receiver，二者不能进入普通 copy 等价类。actual 不能反选 expected。
   存在任意 lookup 不应强迫无关 atomic branch 变成 expanded；每个实际消费者
   与自己的独立 expected 核对。lookup RAISE 不能无判别当 AttributeError。
2. `reuse_capture`：原 Operation 没有能替代 lookup/result 链的 attribute 字段；
   source call inventory 只有候选元数据，不能当原结果端口。真实归档19 reader
   不识别新 enum 字符串，故选择 Program20，并对 envelope 降级明确拒绝。
   原1–19 family与字节保持，独立19 oracle由冻结旧encoder生成。
3. `value_resource_review`：IS_COMPLETE 只检查了 READ/bool/branch，尚未解释
   对最终 gate 的限制。本轮沿原 routes 增派生 frontier，不加 wire。静态 CFG
   潜在 NORMAL 不是成功发生；当前 complete=true 的条件冲突报 False+gap。
   callback 后 snapshot 不当前则 None，历史 bool 保留，实际发生矛盾留P3联合。
4. root：接受上述范围；拒绝本轮加组合 RequestPacketTrigger、通用异常类别
   谓词、新 producer/SSA、跨 callee 无支持的 session 推断和新 backend。

## 明确仍未解决

- lookup missing-method 的完整类别/分支/原注入包 fallback；RAISE packet 与
  injected packet 不混。完整 F21/F22/F23 不因四个新规则而关闭。
- 同R跨多次驱动的 HOLD/COMPLETE/复用拒绝、R2竞争及跨callee session摘要；
  本轮单次 predicate/gate 不冒充完整 F16/F17。
- X25 两cut、X26 helper/session/release、X27 原执行发生组合，以及全部16组。
- 自动源码恢复、运行时/native身份、全 M0–M2、LeWM变换或性能数据。

## 验收纪律

三路实现文件所有权分开；测试顺序运行，无并发测试/工作负载。
保留每次失败及精确源码/命令，最终相关定向前所有作者冻结。
全部16组 ready 后才统一 component、干净提交和一次 frozen full。
