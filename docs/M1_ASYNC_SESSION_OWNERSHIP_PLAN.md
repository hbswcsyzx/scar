# 原 F16：活动 session、竞争读取与后续请求

2026-10-19，基线 `f22d64196d2f706c66e99f7acb4bcffa8373a98c`。
上一门为 VERIFIED_PROGRESS，1907相关测试/870稳定源码；本轮起点重核checkpoint。
原 M0–M2、F12–F24/X25–X27的16族、P5及M2原113构造/196字段范围不变。

## 1. 模型判断

核心实体仍为 Operation / Value / StateLocation / Region / Resource。
HOLD(R,B)是原有支持版本的有序关系，表示活动session；body frame Running、
暂停、terminal历史F和request本身的initial/complete分别表达，不能互换。

现RequestStateCondition只有R的initial/complete；BodyStateCondition表达body
phase，现async profile又排除它。原StateLocation/READ/own bool/BRANCH能装下
完整原图，但缺少“该READ检查B是否有活动session”的typed语义锚。

采用薄 `SessionOccupancyCondition(body_use,state_sites)`，嵌入原
AdmissionPredicate。它只命名原B Use和原READ sites，不存truth、holder R、
新phase或额外可写状态。独立于BodyStateCondition，避免把占用并入frame phase。
主体B从本driver receiver的独立RequestCreate/association来源核对；没有实际
R2 BodyDrive时也必须可查，不能借未来Drive倒推B。

新subject为Program24能力；旧1–23无能力图字节和Execution8不变。旧wire不能
偷带新subject。只扩这个必要准入；初始ASEND的body/None联合能力后续原门另验。
共用普通predicate shape/bool/READ检查与R/B owner检查分离，取消将R伪装成body
的校验proxy，旧wrong-request及bool拒绝必须保留。

## 2. 原生观察与固定合同

参考CPython 3.14 `Objects/genobject.c` 的 `async_gen_asend_send` 与
`async_gen_unwrap_value`：
https://raw.githubusercontent.com/python/cpython/3.14/Objects/genobject.c
本机conda lewm Python3.14.7小实验另存版本/脚本SHA/12个观察，不凭文档代本机。

第一次断言错误假设inspect.getasyncgenstate必返回SUSPENDED，真实失败/脚本已
保留。inspect首先读ag_running，故该API不能作为frame执行与session占用的
独立分类器。第二次分别记录ag_suspended、ag_running、ag_await及inspect结果。
实验看到R1 await时suspended与active_session同时True；R2首次竞争失败后不可
重用，R1仍继续到第二await和item完成。初始nonNone ASEND失败又保body Created。
这些只证明本次原生观察，不建立自动恢复或全部native实现适用性。

拒绝合同必须组合R2.initial检查与B占用检查。R1后续step可绕过首次检查。
占用True单独不代表任何请求都拒绝；R2 COMPLETE不推出B空闲或R1 COMPLETE。
不同CreateID不当作物理对象不相等证据。

## 3. 分门落实与验收

| 节点 | 交付与验收 |
| --- | --- |
| O0 | 三方原合同/代码审读、原生反例与本计划冻结；不加backend/detector |
| O1 | 新subject精确类型/非空原READ、R/B主体分离、公开row view与Program24；旧codec/wrongR/bool/拒绝接口守恒 |
| O2 | 一B、独立Create R1/L1与R2/L2，R1 AWAIT/HOLD→R2 initial/occupancy拒绝own N/R/fullstate→caller准确catch→R1 Resume/AWAIT/item COMPLETE；R2无假body segment/Drive，body共三段 |
| O3 | 派生occupancy_history READ查询：全部原SessionUpdate库存；HOLD的准确AFTER/ownNORMAL、源R/B/全state inputs/support、同B、完整原calls/CFG/效果保持与当前READ bool分开；COMPLETE/ABANDON不推出全B空闲 |
| O4 | 已知getter/明确普通RETURN的新完整区间正例；原opaque主路径与旧R3四阻断保持未知，错B/缺原source/actual Use/transfer、budget1不得补成功。新known子图须展开真实原操作与完整边界，不翻旧opaque标签 |
| O5 | 独立原条款核表、相关回归保原1907精确身份、历史失败源字节/命令/JUnit/源码指纹/checkpoint、commit/push。没有整原F16证据则保OPEN |

原初始ASEND的R.initial/B.Created/latent SEND[0]联合控制仍是后续独立原义务。
R3原四内容blocker保留；原sameR两调用/三stepping及scheduler packet不重做。
完整F16及其余八族、P4组件/冻结全仓、P5/M2须各自验收，不能以本门局部通过
关闭整个模型。M0–M2齐备后先向用户讲解，再做M3自动lowering/M4实际对应。

## 4. 写入与执行责任

root：本计划/档案/Git，subject/protocol integration、普通shape校验抽取、
动态 `ExecutionIndex.session_occupancy_history(read,budget=4096)` 与新动态unit。
A：仅NEW `scar/ir/program/session_occupancy.py`、
`tests/unit/test_program_session_occupancy.py`，静态主体/原ports/branch关系。
B：明确授权旧 `scar/ir/program/codec.py` 及仅NEW
`tests/unit/test_program_session_occupancy_codec.py`，Program24严格能力门控。
C：仅NEW `tests/fixtures/program_async_competition_graphs.py`、
`tests/fixtures/execution_async_competition_graphs.py`、
`tests/unit/test_execution_async_competition.py`，完整两R供图及捕获。

作者只改自己文件，不执行Python/pytest/probe/compile/Git；需要别文件先报告。
全部源码作者明确FROZEN后，root独占串行所有解释器。首红先保准确字节再修，
不删除失败用例或改变原分母。所有图为供应模型，不冒充自动LeWM拆解和加速。
