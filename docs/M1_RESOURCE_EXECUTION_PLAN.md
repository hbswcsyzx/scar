# 资源执行接口：设计、实现与自主验收

基线：`309fb359be8665fc90979f270a6d4e4d20c6eb85`，D2.4 已验收。
本批补第一阶段 M1 的资源实例、工作、完成与消费者可用关系；仍遵守
模型→建图→化简。没有新 detector/backend、源码 lowerer 或重型 LeWM profiling。

## 1. 必须解决的实际缺口

现静态 ResourceDefinition/Requirement/Use/Location 已接原 ProgramGraph；
没有动态 realization、handle lifetime、工作 generation 和 typed ready。
v2 OperationInstance 是另一个静态 definition 空间的发生，不能按名字等同 core
OperationID；Materialization.ready_event 的字符串也不足以确定哪个工作已完成。

本批先确定静态、动态、证据三层之间的端口关系，不在 ProgramGraph 填入一次运行
的实例或 ready=True。原 producer/Use/StateAccess 仍是唯一程序依赖与状态来源。
工作提交、工作终结、队列有序消费、CPU 可读和文件持久化分别建模。

## 2. 有限实施与验收节点

| 门 | 交付 | 必须有的验收证据 |
| --- | --- | --- |
| R0：合同收敛 | 审查已有模型/工具、最小 execution occurrence 接口、resource/handle 代次、work/outcome/ready 的准确范围与迁移路径。 | 三份独立预审；本机有断言的资源/异步小程序；官方协议与本机库版本依据；逐项 root 决定，没有实质未决身份/关系/端口义务。具体 exact records/wire 在实施门冻结，设计门不冒充产品已实现。 |
| R1：实例与对应 | typed run/activation/operation/value/Use occurrence 基础、ResourceInstance/realization/requirement binding/handle lifetime 与 core/v2 的精确外键；明确 snapshot 和原证据。 | 同一 Create 多发生、entry-owned requirement 跨内部使用、dup 与不同 open、handle close/rebind、外部实例、缺失与冲突；严格 codec/查询并保留旧格式。 |
| R2：work 与 ready | 精确 submission、资源终结、event record generation、order/visibility 关系、materialization/allocation/content 的版本化 ready requirement。 | enqueue 未完成、旧 event 代次、同队列与跨队列依赖、旧 allocation/内容、部分失败/取消、错误 consumer domain；有序设备消费不强制 CPU synchronize。 |
| R3：组合与公开面 | 通用读文件→物化→提交计算→等待/消费→写文件→flush/close 的模型组合；明确 source/runtime/native 对应缺口。 | 原端口可回查、缺失/矛盾不静默覆盖、全部旧身份/历史 wire 保留、独立复审、组件门和一次冻结全仓、原失败与指纹归档推送。 |

R1/R2 是同一 execution model 的有序子项，不能各自另存一套 occurrence、state
或 materialization。若 R0 发现必须调整切分，先在合同写清理由，不硬套初始计划。

## 3. 证据与完成边界

- 本机 stdlib CPU 小程序只约束语言/OS/异步接口；CUDA 规则以官方文档及本机安装
  源/header 版本为据，不假称运行了 GPU witness。
- UNKNOWN 表示某条对应或条件证据缺失，必须有具体原因；结构仍要完整表示。
  程序结构合法、观测事实、规则适用和优化授权分别报告。
- 每门保留原命令、版本、失败/修正、源指纹；已有验收结果不为文字改动重跑。
  产品源改变后先定向检查，最终 clean 冻结后一次全仓，运行期间不改源/文档。
- 这一批通过仍不关闭 typed selector、完整 literal、logical provenance 及 M2
  构造协议守恒。M0–M2 全部完成后按用户约定先汇报讲解，再进入自动建图阶段。
