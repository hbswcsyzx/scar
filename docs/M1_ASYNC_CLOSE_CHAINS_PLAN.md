# F19完整链：计划与验收单位

2026-10-20，起点 `c02e973c151ecda8808c3cfa245339840edb9f24`。
上一门为已推送的条件值来源桥，292相关项通过；当前已知focused目录2325。
上一goal turn属于真实进展：产品/测试/报告与独立审查已落地并提交，不是等待。

本轮返回原[F19计划](M1_ASYNC_CLOSE_CONTINUATIONS_PLAN.md)，不继续扩同类来源
helper，不新增detector/backend/LeWM规则，不改五类实体或先假定schema需变。
完整M0–M2及原113构造/196字段保持；不以本轮易通过的子集替换完整F19单位。

## G0：先用已有图和观察判定真缺口

root在全作者FROZEN时运行原finished请求的公开body_state_history，按原terminal
publication筛准确candidate，分别记录READ主体、历史Drive主体、Create handle、
所选own R/B值、source支持、host/state区间和缺采。新value_source_pair只消费
真实已声明slot合同；原无合同就Unknown，不能从Create.body或分支True猜边。

既有CPython3.14.7探针已观察真实graceful/illegal/finished后续共22调用；先重读
并复用准确结果与固定genobject.c，不为已有观察重跑无关native矩阵。
三个只读子任务审原第1项、后两条组合和独立验收边界；全部无写/解释器/Git。

G0已运行：917/51da77…源码前后稳定，4.702666380442679秒。原无identity的
Return→newThrow和Raise→newClose两个同图公开history均None/观测branchTrue，
source/read caller chain与terminal host route均有，Drive owner及当前subject
缺独立identity，stored合同均0；通用来源仍None正确。报告在
`model_async_close_full_chains/baseline.json`，不将原图缺事实叫查询失灵。

独立审查收敛：第1单位可复用四格finished图，分别显式提供当前B/原Create/
Drive/publication的scoped ObjectIdentity条件守卫，并保R ownN和当前READ ownN
的原actual链。它不等于恢复R字段来源，不要求先展开opaque整个Create；原无
身份图必须仍None。构造失败/retry复用有限反例，不重复全四格全乘积。

## 原F19四个验收单位（不缩减）

1. 真实BodyReturn(None)/BodyRaise→F后，同B新athrow/aclose无Drive回复；sameR
   retry与newR分开。准确constructor own N/R、caller/handler当前全state及包来源。
2. graceful aclose：GE→finally AWAIT/HOLD→同R以本次S恢复→真实terminal→body层
   与request回复层转换；不能把新异常构造当旧packet copy。
3. illegal close-yield：错误构造之前R完成、B仍Suspend；sameR拒绝/newR无Drive，
   随后同B恢复finally及真实终结。native closed bit、活动session、F和release分开。
4. 对原输入/ports、全state、host/caller、错误F或提前release、删附件、一次实例
   缺采和tiny budget有实际正反例；完整兄弟不补缺实例，不用observedbool做证明。

graceful验收共prime/close-AWAIT/sameR-resume三次实际Drive/segment；包括finally
的C1和全部saved/current slots，Return、GeneratorExit和普通异常三条出口可共
原CFG有限选路。两层reply按第一packet→精确matcher/ownbool/原branch→新
constructor ownN/R→packet/host表示，不强迫新旧包copy相等。

illegal链包括prime、close失败、sameR retry、newClose/newThrow无Drive、newNEXT
恢复finally六次driver activation，只有三次实际Drive/segment；五个request
Create保持相同B。非法yield后提前release拒绝，最终真F后有异步窄release正例；
窄release保UNKNOWN/MAY_NOT_COMPLETE/NOT_GUARANTEED，不宣称物理free。

已确认生产接缝是三处对ASYNCGEN_CLOSE_YIELD_ERROR的expected_post降None：
`program/async_session_sources.py`、`program/protocol_async.py`、
`execution/resumable_sessions.py`。原ASYNC_YIELD已经分类COMPLETE；native固定
yield_close在错误构造前清active并关闭R，真实F只由Return/Raise种，不能由
Suspend补F。先供完整图首红再统一分类，不依可选adapter恢复COMPLETE。

`execution/resumable_sessions._hosts`当前只投影第一层adapter是源码边界，未有
完整两层图反例前不称实测bug/缺类型。先用既有ExceptionMatcher和原constructor
表示完整两层，只有实际接线缺口才薄修查询；不新增enum/schema或放宽现CLOSE
规则必须接精确DriveResult的合同来迎合图。

## 建模责任与可接受边界

当前有类型能表示的真实展开，使用原Region/Operation/Value/StateLocation/Resource
和原Use/CFG/CallActivation。新R allocation以后才可有R-owned store；不能把own
future result作为原constructor pre-owned输入。不可展开native保准确边界，且
明确模型能表达、所供图可核、与真实实现对应三个不同结论。

不造request专用值来源规则、不加全局copy/identity union，不伪造无写区间或
补produced Reference precision。若独立Drive owner→Create handle或区间仍缺，
必须单列，不能因当前READ已接就关闭F19。

## 实施前冻结与自主验收

G0结果与三个审查返回后，先确定真实最小实现范围、文件所有权和完整单位的
证据映射，再授权写。root独占串行Python/pytest/probe，所有作者FROZEN后才运行；
保原首败源码、命令/JUnit、前后指纹。直接受影响回归足够后停止可选扩大。
每个完整单位有明确报告；全部F19条件成立才申请整族限定接受，然后返回原
F20/F22/F24/X25/X26/X27与P4 component/full/P5/M2整阶段门。

原九族/await A–H限定接受保持；M3自动entry→Python shell/FX/Export子Region
与LeWM自动拆解仍在建模阶段之后。阶段真正完成后先向用户解释，不加速宣称。

## 实施接口与唯一所有权

B第一批仅NEW `tests/fixtures/program_async_close_chains_graphs.py`，入口
`async_close_chains_program(*, route='graceful-return') -> (graph, details)`，
route四值 graceful-return / graceful-ge / graceful-ordinary / illegal。
原图保所有constructor N/R；actual选择通过准确原edge choices供给，不为此
展开参数乘积。metadata的body/requests/stages/reply_stages保原records、ports、
paths、fullstate以及实际finally的C1/saved slots。不得只换旧cleanup模板flavor：
prime之后的GE packet私有resume入口才进入finally/C1；graceful-return以
CleanupReplace新RETURN(None)覆盖原GE pending，graceful-ge和illegal续体
CleanupResume原GE，ordinary以新异常pending替代，均再真实Route/Dispatch终结。

A第一批仅NEW `tests/fixtures/execution_async_close_chains_graphs.py`、
`tests/unit/test_program_async_close_chains.py`、
`tests/unit/test_execution_async_close_chains.py`。供采接口
`finished_frame_identity_execution(terminal, request, constructor_raised, retry, instances)`
和 `async_close_chains_execution(route, instances, choices)`；参数均keyword。
复用原capture构法、原端点和真实CallActivation/ResumeIngress，不因noDrive造body
segment。独立identity明确是供采条件，不从expectedBool/协议类别猜同B。

root负责计划、G0/首红/修正/回归归档、必要原消费者接线协调、报告和Git；
C独立只读审查，不执行/不编辑。作者均不得运行解释器、pytest、probe或Git。
第一批先落完整新图/测试，B三处production分类暂不改；全部作者FROZEN后root
保原源首红，才授权B精确三处修改。若两层host投影真失败，仍在其既有exec文件
薄接入，保普通copy和原CLOSE合同；其余产品/旧fixture/test无预授权写入。
