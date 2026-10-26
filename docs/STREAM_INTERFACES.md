# 程序可见的流接口

可选入口：

```bash
python -m scar.cli trace --capture-plan PLAN --capture-plan-sha256 SHA \
  --stream-interfaces --out fresh-trace -- python program.py
python -m scar.cli query-stream-interfaces --metadata META --sha256 META_SHA
```

这不是完整FD表或新程序图。它给已有CALL attempt附加实际builtin流接收者、接口
效果及C完成；保原InvocationKey、CapturedSite和CALL原行依据。`BytesIO`与文件流的
read/write/seek/flush/close用同一接口表达，流种类作为类型信息。

只识别精确stdlib builtin类型及实际C描述符/绑定方法。子类、用户替换的方法和
不在计划内的内部实现不会被冒充builtin。接收者沿原weak-reference协议标识；
引用仅在原capture命名空间内有效，同fd数字或路径不参与身份合并。

接口声明读取/可能写入CONTENT、CURSOR、BUFFER、HANDLE、BACKING_CONTENT等状态
角色，保留异常；`effects_complete=False`。C_RETURN、C_RAISE保留实际控制完成。
后者不提供返回对象或实际读写字节数，也不证明flush可见性、持久化或GPU ready。

采集器不包装/替换流对象，不读取内容、文件名或cursor，不主动调用fileno/tell/
flush，不保存Tensor数值。只保弱接收者引用和小metadata，没有跨callback强持有流、
frame或callable。CALL的依赖C_RETURN/C_RAISE回调复用同一个sys.monitoring tool；
实测CPython3.14.7的local mask规范化为CALL，因此不把依赖事件位误当独立mask。

事件保存在`stream-interfaces.PID.jsonl`，关闭metadata绑定原call/frame文件收据。
普通reader核原CALL行、actor/site和固定接口声明；owned capture coordinates也会
纳入两个成员及准确原输入收据。它不替代source/ABI、完整effects或backing身份证明。

实际结果在`artifacts/experiments/stream_interfaces_main_20261026/`：

- 首次target虽exit0，但错误的mask比较导致CALL channel失效、0条IO；保留原失败，
  不以退出码当采集成功。修正了CPython依赖事件mask处理。
- fresh普通采集exit0/2.157s，7 BEGIN、6 C_RETURN、1 C_RAISE、0 UNOBSERVED；
  6095B，无stream错误，reader逐条接回原CALL。
- fresh GPU+OS联合采集exit0/25.687s（插桩时间），同样7条接口，CALL channel
  0 instruction/0 gap/0 error。普通coordinates验证83成员/8,644,413 raw bytes，
  精确stream membership已回读；Kineto实际1 H2D与1 kernel。

当前是观察和接口连接。实际参数/结果内容、流到准确backing资源、canonical source
状态端口以及LeWM完整输出链仍需后继连接；不能据此声称所有IO已经完整建模。

## 从观察连接到已有源码图

`scar.analysis.source_stream_interfaces.read_source_stream_interfaces` 接收普通
`CallOperandTrace`、`ProgramInventory`或已绑定的`SourceBodyAccess`及原stream metadata。
它复用原CALL、CodeWitness、源码CallSiteLink及已有ProgramGraph，不另建一套IO执行图。
结果保留callee Use、有序actual Uses、world Use/Location、正常与异常CompletionResult。

旧inventory缺少某个body时，可显式提供同命名空间的完整`SourceProgram5`和独立
`SourceLanguageOptions`。入口先做普通`SOURCE_REPLAY`、核原snapshot/definition/CodeWitness，
再匹配原CallInventory。这种局部输入标为`SOURCE_REPLAY_LOCAL_BODY`；不修改旧inventory，
不冒充该body已正式发布或已经绑定整个运行。

真实联合采集样例已用这条路径连接7/7次流调用到原源码CALL和规范端口：6次C_RETURN、
1次C_RAISE；函数图329个操作。结果及原ID见
[实际报告](../artifacts/analysis/source_stream_interface_core_join_20261026/REPORT.md)。
观测到的接收者token尚未绑定source Value/Resource；实际返回内容、backing身份及持久化
仍未证实。正常/异常静态出口全部保留，不因C完成事件就推断具体结果对象或状态内容。
