# 采集产物的统一执行坐标

状态：第一阶段中的 membership 连接器；不是完整程序模型，也不授权优化。

## 实体与边界

复用 `ExecutionRun`、`ProcessInstance`、`HostThreadInstance`。连接器不新增一套
执行图，不按 PID 相等、时间接近或文件名相似来合并采集。它只回答：给定的原始
产物属于哪个已核验的采集进程；哪些 Linux 线程由明确的 clone/fork 关系关联。

`scar.trace.capture_coordinates.bind_capture_coordinates(capture_dir)` 返回：

- `run`、`processes`、`threads`、`target_process`：既有 IR 类型。
- `process_for(artifact, pid)`：只接受已绑定的 artifact 字节身份和选择器，未知返回
  `None`；OS 逐线程产物的选择器为对应 native TID。
- `thread_for(artifact, token, namespace)`：只有 `linux_native_tid` 可查询已核验的
  OS/Kineto host 坐标；Python ident、ETO token、GPU lane 不会被解释成 Linux TID。
  未连接时返回带 EvidencePoint 的 `UnresolvedHostThread`。
- `artifact`、`payload`、`report`：机器可读 membership 与证据；调用方可保存和绑定
  其精确 SHA/字节，而非创建新的捕获身份。

## 机械核验路径

1. 读取关闭且无失败的 native collector manifest，核 PID、ETO/Kineto 的共同随机
   nonce 和原始命名空间。
2. 核验 calls、operands 和 native 的精确原档哈希、字节及声明。operand 的三项
   base manifest 必须精确指向同 PID 的 codes/events/meta 文件。
3. 从 OS 原档查找唯一成功 `execve`，argv 必须完整等于 `run.json` 的成功命令。
4. 从成功且无歧义的 clone/fork 建立进程/线程祖先关系；不清楚的 actor 保持 OPEN。
5. 核验目标进程创建 calls/events、codes、operand events/meta、native manifest 的
   `O_CREAT|O_EXCL`；核 nonce ETO 创建、Kineto tmp→final rename 和 collector manifest
   的 nonce tmp→final 发布。
6. 如果存在 function-environment sidecar，events/meta 必须成对保留。核 schema、
   PID、精确 events 路径、SHA、字节及行数声明，并要求两文件均有目标进程的
   `O_CREAT|O_EXCL` 证据。这只证明产物所属，不证明闭包内容或 canonical 入参绑定。

## 两种保留方式

- **plain**：没有 `archive-index.json` 时，只读取 capture 根内精确相对名称的普通
  原档；不会猜测 `.gz`，不会跟随 manifest URI 去读外部路径。
- **lossless archive**：存在 manifest 时必须为 `scar.lossless-capture-archive` v1，
  `verified_roundtrip=true`，每个映射都有原始和压缩字节的 SHA/长度。逻辑与实际路径
  必须处于原 capture 命名空间，重定位后仍在给定根内。压缩产物逐项核原始解压字节
  和压缩字节；不静默退回一个不匹配的 plain 文件。

两种方式均有总原始字节和 OS 行数上限。原始文件来源仍以调用方给定的捕获目录、
固定采集器契约和无外部篡改为条件；连接器不会将自己的观察当成安全隔离证明。

## 尚未建立的关系

采集窗口及线程生存区间不完整；未支持的 OS 行、缺失 actor、collector 丢弃或错误
都进入 `open`。Python→Torch occurrence、source/world effect、逻辑值来源、Tensor
alias、materialization ready、资源真实完成状态仍需要相应适配器提供证据。
`whole_model_established` 与 `transformation_authorized` 始终为 false。

旧成功采集的实际核验已得到 260 个成员、5 个进程、252 个线程、705,569 行；这是
所属关系的结果，不是完整模型覆盖率。plain/环境 sidecar 扩展须由最新成功 LeWM
原档实际执行后再报告结果，不以实现状态冒充运行结果。
