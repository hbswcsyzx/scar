# 当前frame身份分支：实际过程

2026-10-20。完整原范围及本批边界依[M1_FRAME_IDENTITY_GUARD_PLAN.md](M1_FRAME_IDENTITY_GUARD_PLAN.md)。
F19、整阶段及自动stored-reference来源恢复仍OPEN。

## G0 / G1

基线0bf37d2及上一checkpoint复核通过，受保护仓库均保持原HEAD/clean。
root先运行`diagnose_history.py`，在904/ec1969…同源供采上发现：准确目标terminal
的ports/chains/host route已完整，唯两处body身份普通copy缺；预算4505/1m未截断。
该诊断不执行native target或LeWM，不是新的runtime profiler数据。

三路只读审查否定Create+host order即可推出后续字段不变。现存StateAddress与
ContentRead不能证明stored Reference payload关系，不能将此缺口翻为纯/immutable。
设计改为复用已有独立当前ObjectIdentity声明，回答本次主体是否同一frame；
来源恢复继续独立未完成。ObjectRef没有epoch字段，准确namespace由artifact及ID
表示，不允许裸Python地址跨世代猜相等。

冻结计划后先补新正例，全部作者FROZEN。root串行运行
`current-object-history-counterexample`：906文件指纹
`a9951ba4679f1377f54af17cde0a8d7f98a156fba654299c89245a2a82df617d`
运行前后一致。程序与capture校验通过，唯一测试在实际语义断言expectedNone与
所供身份条件下的预期True处失败（7.62秒）；不是collection或API不存在。
首红源码、命令、输出、JUnit原样保留，然后才放行产品和有限反例写入。

A负责通用identity receipt及公开委托，root负责history集成，B只加新fixture/test，
C独立只读复核。各作者不执行解释器/测试/Git；root在所有源码冻结后串行验收。

## 第一轮产品与有限反例

`first-joint-identity`在907文件指纹
`8181170118125f9cd641053c2a63bde8b59c46614aecfd7fe4a3564f57a951b0`
上稳定运行：12 PASS、1 FAIL，127.58秒。主正例已经将两个独立实例各自的历史
条件性闭合，ordinary copy仍未知、内容保持/native适用仍未知；缺采、scope、目录
刷新、预算和删除附件的相应节点通过。

唯一失败在WRITE反例fixture构造时：原Reference alias range/targets未知，却将
写操作标为effects_complete=True，已有canonical校验以incomplete_alias拒绝；
实际身份反例尚未执行。这是fixture完整性声明错误，不是产品误用旧B1历史。
保原首败字节后将改为effects incomplete，不为绿测伪造alias信息。另只补一个
ValueGraph registry扫描预算分支，避免新支持分支完全未验证，不扩大原矩阵。

## 修正后的直接复验与独立审查

`corrected-write-and-value-catalog`仅运行上述两个尚需核实的节点，2 PASS，
16.39秒pytest / 17.301198605448008秒wrapper。907文件指纹
`b7a6ad77e48d49e7055e588b75e5d9f4380a8023339f98bfc396b113054fb3aa`
前后一致。WRITE后的当前READ独立声明B2，不借旧B1的F；第二实例仍可独立成立。
ValueGraph有100个前置注册binding，充足预算支持所供身份，固定预算16截断为None，
仍保留两个原端点；没有依实现计数探测一个恰好通过的预算阈值。

C对最终五个产品/测试文件只读审查，无阻塞；未执行解释器或修改文件。确认身份
与ordinary copy/来源/内容版本分离、peer比较局部化、fresh目录/hash、预算及
Create/Drive/当前READ/F各自端口要求。完整SHA、未覆盖范围见归档independent-review。
随后root在全部作者FROZEN、相同907来源上串行执行23模块直接受影响选集；
最终结果以验收报告与原JUnit为准，不将本次供采查询冒充native或LeWM实测。

`verified-current`最终231 PASS，342.58秒pytest / 343.4434034684673秒wrapper，
运行前后均为上述907/b7a6ad…指纹。14个新身份，217个既有身份，包含上批196项
全部原ID；未重跑整个2121目录。没有skip/error/failure。两处受保护工作树再次
核为原HEAD/clean。最终checkpoint、普通commit/push及远端SHA在归档后独立核验。
