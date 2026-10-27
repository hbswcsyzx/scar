# Async terminal：实际观察与实施记录

2026-10-19 开始，2026-10-20 续。基线 `54118247d4ff4c764dbe6f66493bc8609041f24b`。
状态：**最终2104项 affected 通过，原F18条件性结构接受；F19及完整阶段仍开放。**
[冻结计划](M1_ASYNC_TERMINAL_PLAN.md) 保原十六族、M2 113 构造/196 字段和阶段门。

## 已观察证据

档案为 `artifacts/experiments/b1_call_operands/model_async_terminal_semantics/`。

| 记录 | 实际结果 | 限定意义 |
| --- | --- | --- |
| native-probe.json | 22 条本机调用观察、2 条只编译观察，全部 body 最终关闭 | 两 Stop* 转 RuntimeError/cause/context、普通异常、finished frame 新 request、非法 close-yield 后的同 R/新 R/续体、正常 close 的 await handoff |
| return-source-probe.first-failure.stderr.log | 探针 ValueError：错误假设 module symtable 只有一个 child | 本机还有 __annotate__ scope；不是 SCAR 产品失败，原脚本和日志保留 |
| return-source-probe.json | 修订后 5 条编译/AST/symtable 观察，目标 body 执行数 0 | explicit None 非法；裸 return/嵌套 sync return 合法；仅嵌套 yield 与默认参数 yield 的归属不同，symtable 不替编译合法性 |
| initial-source-denominator | 1 项实测失败，0 错误；893 文件稳定 | 删 AsyncSessionOutcome 后，已知非 None 的原 BodyReturn 被旧 validate 接受；旧产品字节仍全部为前门版本 |
| first-joint-authored | 38 项：20 FAIL / 18 PASS，0 ERROR；899 文件稳定 | root 误把 ScopeID 当对象、caller 声明未绑定 normal exit、Unicode compile offset 的错误前提；原失败不删 |
| syntax-offset-probe.json | 4 条 compiler/parser 观察，目标执行 0；仍同首测 899 文件 | parser 字符位置与 compiler 语义错误 AST UTF-8 字节位置不同；不能统一按字符转换 |
| revised-joint-terminal | 40项：2 FAIL / 38 PASS，899稳定 | 静态误要求 later-helper 包复制 body 包；budget1的 predicate port None 解引用 |
| type-comment-probe.json | 3种模式：ordinary compile/AST 接受、typed AST拒绝，目标执行0 | 可选 metadata 不能给语言合法性定罪，fallback不可伪 frontend atom |
| precise-terminal-residuals | 43 PASS，899稳定 | 原两缺口及 type-comment 有限修订通过，尚未覆盖 ID 排序和静动接缝 |
| canonical-choices-counterexample | 2 FAIL，899稳定 | 错误拒绝当前包、接受仍可用的旧包；canonical choice排序不等于CFG发生顺序 |
| ordered-terminal-residuals | 45 PASS，899稳定 | 原CFG重放取最后 ownRAISE，完成全槽付共享预算 |
| verified-final | root停止自己的pytest，rc2；379 PASS/899稳定 | 独立审出真实静动接缝后早停；完整保留，绝不是最终通过 |
| static-dynamic-failure-counterexample | 1 FAIL，899稳定 | 后继普通helper无SessionUpdate仍会 ownRAISE；动态误接前包 |
| unified-terminal-residuals | 46 PASS，899稳定 | 静态按原CFG，动态按actual suffix取当前包；旧包不能替代 |
| verified-current | 2104 PASS / 0 FAIL/ERROR/SKIP，899源稳定 | 原2058精确身份全部保留，新46；这是affected门，非组件/冻结full |

前两个成功探针在原 892 文件/f8e32575… 运行；首红在仅加一份新测试文件后
运行，完整指纹 `b58378e2e0ba1145e1ae8245f276166d7cb026731f82b7c9ab7efb432f665a53`。
首红 pytest 0.90 s、wrapper 1.584121 s；命令/JUnit/日志/差异源码/前后指纹保留。

## 撤回的建模前提

1. 不能默认将 Stop* 转换放在 Driver 的 BodyRaise 之后。固定版本 compiler
   handler 在 frame 内运行 intrinsic，再真正 RERAISE；现用原 Region/operation
   展开，而非补一个外部 async adapter enum 迎合旧同步高层 fixture。
2. `ExceptionPacketDefinition` 不冻结 exception 的 cause/context 属性；这些
   来源和状态写必须单独连接。native constructor 身份不是由名称证明。
3. native `ag_closed` 位未由探针读取；公开 inspect 的 AGEN_RUNNING 可同时
   ag_suspended=True，不代表 frame 正在执行。request、active session、续体、
   frame/资源终结的合同保持分开。
4. 暂不新增 SourceForm record。已有 source snapshot/span 可承载编译诊断；
   不靠运行值是否 None，也不自制跳过 nested def 的作用域判定器。

## 首轮后实施（历史记录）

root 已把已知非 None Return 检查移到原 outcome inventory，先保 source 分母，
再预算化检查，不依赖可选 session 绑定；BodyRaise 最终 packet 的动态 host
传播仅在实际路径无 source-specific driver adapter 时使用。缺 adapter capture
不能触发该旁路。

独立审查指出后续 NORMAL_COMPLETION helper 实际走 RAISE 时应优先其 own
packet，而非旧 BodyRaise；已按实际 edge、签名 packet slot 和 landing 取源，
缺捕获仍保 None。追加一项通用来源反例，不修改旧 fixture 或偷用 AWAIT 用例。
首测 root ScopeID 使用已修；source compilation 的 parser/compile 两阶段定位
已按新真实探针修正，保原精确 Return span 断言并新增一个 parser 反例。
上述为首测后阶段的实施记录；后续实际失败和修订见下文，不按作者自核称通过。

三路作者仅写计划授权的 NEW 静态、动态和 source-compilation 文件；全部冻结后
root 才执行测试。原 Program26、Execution8、旧测试/fixture 字节保持；原 2058
身份必须保全。当时尚无新增用例通过结论，后续46定向已实测通过；统一选择
结果见末节，F18/F19、P4/P5/M2 和完整第一阶段均不由此前缀预先关闭。
本轮不添加 detector/backend，不修改 LeWM，没有变换或加速比。

## 后续最小修订与最终运行

[残缺补充](M1_ASYNC_TERMINAL_RESIDUAL_AMENDMENT.md)先冻结已测两缺口与metadata
误判；[顺序补充](M1_ASYNC_TERMINAL_ORDERING_SUPPLEMENT.md)保两helper反名正反；
[静动补充](M1_ASYNC_TERMINAL_STATIC_DYNAMIC_SUPPLEMENT.md)保实际后继ordinary
helper失败来源。旧生产最终仅4份，NEW7份，原旧test/fixture字节没有改变。
Program26/Execution8没有变更。所有解释器/pytest/probe由root在作者全部冻结后
串行运行，独立审查只读，未运行解释器。

最终46定向 pytest27.07s、wrapper27.841770s，899稳定源指纹
`37dfff022d371ee43a66e24d481e09c4b6933a81230e51eb540c1fbabfd2faa8`。
这是结构测试时间，不是LeWM性能结果。已有独立审查指向相同最终源字节。
源编译query的目标模块始终未import/exec；native-probe另有22次自建fixture调用，
不能把原计划“目标执行0”的源级边界误读成从未做实际native观察。

两份 residual 辅助探针分别在已拒图的public/prepared index获取上失败，脚本与
stderr原样保存；没有获得 completion walker 证据。独立type-comment探针成功。
所有原首败和源码快照保留，最终 acceptance/checkpoint 在统一选择完成后生成。

## 最终收门

首次archive审计捕获中断JUnit的额外匿名行：suite/stdout为379项已完成PASS，
XML实际有379具名行和1个无classname/name、time=0.000的未完成占位。保原XML，
记录raw380/named379/anonymous1，只对具名身份做subset核验；匿名项不算通过。
首次审计脚本及真实失败转录留档，最终2104全部具名PASS和源字节不受影响。

最终 verified-current 2104项全部通过，wrapper 963.982687s，
899稳定源 `37dfff022d371ee43a66e24d481e09c4b6933a81230e51eb540c1fbabfd2faa8`；无旧test/fixture字节修改或case迁移。
原九族条件性接受，F19/F20/F22/F24/X25/X26/X27七族、P4 component/full、
P5/M2原113/196和第一阶段仍开放。保护仓库由checkpoint复核，正常commit/push
后核远端完整SHA、0/0和干净。LeWM自动建模/可信变换/加速比均未获得新证明。
