# 调用不是统一的函数体入口：真实原档暴露的协议缺口

2026-10-23。**Observed / Verified：分类审计；协议恢复尚未实现。**
这是第一阶段自动连接的具体阻塞项，不是新的detector/backend。

## 1. 已核实的分母

旧272038与当前369749独立读取、完整SHA/大小/metadata核对后，各100,550次CALL
attempt有4,069次唯一entry handshake。其余96,481次精确分成：

| 原协议分类 | 次数 | 目前确切知道什么 |
| --- | ---: | --- |
| OTHER | 88,176 | 保留callee引用和arg0观察；没有该variant的code/layout，不知道完整dispatch实现 |
| EXACT_METHOD | 40 | 是精确MethodType引用；尚未保留/核验receiver、底层函数、绑定规则和入口 |
| 项目外EXACT_FUNCTION | 7,320 | 有原code/layout；采集器没有在此项目范围外建立同步pending |
| 项目内EXACT_FUNCTION、无握手 | 945 | 8个code均带CO_GENERATOR，descriptor.flags与layout.flags对应 |

945次generator-target调用与945条PROJECT_FUNCTION_CALL_DID_NOT_ENTER同现；原GAP
不改写。详见[原档审计](../artifacts/experiments/first_stage_call_protocol_frontiers_20261023/README.md)
及其完整逐code分类。这里没有声称945个对象已成功创建或945条GAP逐一因果对应。

## 2. 为什么原先一种握手不够

原collector只对exact FunctionType且code在project root内建立_pending；入口observer
以callee code、对象仍存活、caller offset、线程和epoch验证同步body进入。
这个证据适用于一部分普通Python函数，不能作为所有CALL成功的普遍定义。
route builder却先统一要求唯一handshake，才分析其它条件。因此同一诊断混合了
不适用的入口协议、范围限制和真正缺失的证据。

generator调用先返回可驱动对象，body在后续next/send等驱动时执行；该对象保留环境
和挂起状态。创建、实际驱动与每次yield/完成必须分开。[Python语言定义](https://docs.python.org/3.14/reference/expressions.html#yield-expressions)
说明这一差别；该在线页面当前为3.14.9，作为语言语义参考，不冒充原3.14.7实现证明。
原CPython3.14.7 collector的flags和代码路径才是本次行为诊断的版本证据。

监控API的CALL发生在调用之前；C_RETURN/C_RAISE也不是任意Python函数的通用返回值
捕获器，不能加两个callback就声称所有结果和参数都已恢复。
[官方事件合同](https://docs.python.org/3.14/library/sys.monitoring.html#events)
须与固定解释器版本的实际实现、完整性和结果来源共同校验。

## 3. 同一模型中的正确连接

```text
CALL attempt + callable/object/environment + 有序实际参数
  ├─ 普通Python调用 → 参数绑定 → body activation → normal/raise
  ├─ 方法/descriptor → receiver与目标解析 → 上述调用或其它协议
  ├─ resumable创建 → 参数/环境捕获 → generator/coroutine对象或创建失败
  │                                      ↓
  │                         drive/resume → body segment → yield/return/raise/close
  └─ 其它callable → 实际派发接口 → source/native/provider活动及其完成
```

沿用现有Operation/ValueOccurrence/Object/FunctionEnvironment、RegionActivation、
BodyDriveExecution、BodyActivationOrigin等身份，不另造可独立修改的调用图。
静态callee种类、调用尝试、创建成功、实际body进入、完成是不同事实；每条边均需
本Run证据。code flags决定应检查哪种协议，不能凭它填充对象ID、返回值或状态。

## 4. 后续实现与验收顺序

1. 先完成已授权的当前Run静态来源连接，以及固定解包/Slice/词法作用域补全；
   旧运行事实仍不进入当前Run，语言新capability不得渗入旧wire。
2. 自动从实际callable kind和code flags生成协议需求清单。将不适用同步入口与
   实际入口丢失分开；保留旧问题，新增有来源的分类，不能靠重命名问题宣布闭合。
3. 普通函数、方法绑定、resumable creation/drive和其它callable各自补全缺失端口。
   优先使用保留原档；无法恢复对象/完成时明确列出必须补采的字段。
4. 待source/控制路径、callable结果、Torch逻辑来源和资源补采需求共同确定后，才
   对原完整LeWM命令做一次联合采集；不为每个小字段重跑episode。
5. 用当前实际分母逐项复核actual/formal/return、对象/环境与drive关系；仅有调用
   分类的数量不能代替这些连接。S3/S4必需项仍OPEN，禁止推进优化。

本次没有修改collector/route guard，没有把OTHER统称native，也没有按LeWM函数名
添加规则。生成器创建不执行函数体本身不是dead work；尚未观察consumer不授删除权。
