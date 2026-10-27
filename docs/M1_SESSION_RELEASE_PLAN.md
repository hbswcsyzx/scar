# D2.3：会话后态、失效与终态引用释放

2026-10-18；实施基线 `817cc0b`（D2.2 已验收）。
本门落实 [D2 冻结合同](M1_DRIVER_LIFECYCLE_CONTRACT.md) §5–6，属于
第一阶段 M1 类型和组合；不扩大 detector、backend、source lowerer 或 Tensor tracer。

## 1. 交付及规范事实归属

1. `SessionUpdate` 两种绑定与 `TerminalFrameRelease`：只引用已有操作、独立角色
   Use、状态访问及真实完成边；新增严格 v14，旧 v1–v13 原字节保持。
2. terminal 历史 F 与当前引用 must-equality E：先沿每条真实边同时改名再合流，
   重新定义忘记旧 incarnation；E/F 固定后单独求解释来源 T，不枚举路径或配置。
3. 当前会话 P：按准确 R/B 对及当前 L 支持版本派生。元数据 after 或 helper 最终
   NORMAL 建立；RAISE 保留实际部分后态且不授 post。普通未知写/回调使旧 P 失效，
   body-only publication 可重基已有 P，不生成新 P，不宣称 world 内容相等。
4. 窄终态 frame 引用放弃：owner 在本点必须有条件性 F；每个 D 域使用当前状态并
   产生实际 after。固定 FrameRules 保留 unknown effects/unraisable/可能不完成/
   不保证 free。真实 raising wrapper 仍按普通 INVOKE 的两条完成边表达。
5. 公开查询和 CLI 只返回原端口及派生声明事实；不新增第二 producer、许可、
   consumed/drop_once 或用户可写的 proof 标志。

F 不证明当前 session、frame still-held、对象 free 或 GPU ready。P 失效表示该点
不能派生该谓词，不自动把原程序判为非法；新 release 声明则必须满足其 F 前提。
同 owner 的两个实际窄 drop 尝试不消费 F，也不自动被判成冗余。

实施澄清：主冻结合同 §5 不排除已有 core 可校验的精确 reference。session 的访问
可指向自身 R/B Use，release 的访问可指向自身 owner Use，其余访问可保持 coarse。
所有 target/selector/覆盖与 alias 义务仍由 core 校验，不由 lifecycle 标签补证。
早期审查附件的 coarse-only 建议不用于拒绝主合同允许的精确表示；保留原附件，
不修改冻结合同或伪造一次修改前的失败实验。

## 2. 计算顺序与效率

core/C0/C1/C2B/D1/publication/no-body 校验 → 新记录的 shape/端口校验 →
每启用 driver 一次预索引 → E/F must 工作队列 → 固定 E/F 上 T 的 union 最小不动点 →
P 的逐边同时改名与 must 合流 → release 前提校验 → 原索引查询复用结果。

本点的 current L 状态组合从已有 StateAccess、callee result 和 edge/formal 派生，
不是新建独立可修改的 world。P 的有限关系和当前支持版本分开计算；解释来源不
参与真值判断。未证相等不当作不相等，未知效果不当作 NONE。

## 3. 自主验收节点

| 节点 | 验收要求 |
| --- | --- |
| 规格交接 | 两种 post 绑定、窄/宽 drop 边界、合流与循环转发没有未决实质矛盾。 |
| records/wire | exact/嵌套/角色冲突；两新表才选 v14，旧 schema 拒空新表；v13 历史期望从不可变基线生成。 |
| 真实图与派生 | Return/Raise/no-body 种 F，Suspend 不种；多来源共享 release、交换错误 owner、部分未结束路径、循环重定义；callback 后 F 保留/P 失效；两种绑定及 RAISE 当前态；相同 B 不同 R。 |
| query/CLI | 返回原 Use/State/Successor 与当前支持；无源码、native、runtime、资源释放或变换授权。 |
| 独立复审 | 交叉只读复核，绑定最终源 hash，原失败保留，不重复运行已有证据。 |
| 组件门 | 对新增义务及既有 D2.2/D1/core 正反例逐条映射；跳过、缺项或源变化不算通过。 |
| 冻结回归 | clean 实现提交后只运行一次全仓；期间不编辑源码/文档或另跑测试；核对原测试身份和 fixture 变化。 |
| 归档推送 | 命令、版本、原输出、失败/修正、逐文件 SHA 与保护仓库检查；文档及进度矩阵保持一致。 |

验收时间只报告分析/测试成本，不作为 LeWM 性能数据。整个第一阶段仍按
[完整性分母](FIRST_STAGE_COMPLETION_MATRIX.md)关闭；本门通过不替代 D2.4/D3、
资源生命周期/ready、occurrence/denotation 或全部构造协议。第一阶段全部通过后
再向用户解释模型并停在约定边界。
