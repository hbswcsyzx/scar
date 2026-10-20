# F19第1批实际过程

2026-10-20。完整范围以[M1_ASYNC_CLOSE_CONTINUATIONS_PLAN.md](M1_ASYNC_CLOSE_CONTINUATIONS_PLAN.md)
为准。此批仅实际终结后的新请求与共用无Drive查询；F19整族保持开放。

## G0 / G1

- 核实基线b2f7e1e、干净tracking及受保护LeWM/main SCAR均未变。
- 前一轮checkpoint已核；最终证据是model_async_terminal_semantics/verified-current。
- 复用固定CPython3.14.7源码与22调用/两编译原生记录，本批不重复相同probe。
- 三个只读审查分别核：finished新R、graceful finally-await、illegal-yield后续体。
  发现原无Drive路径未进入Drive中心查询、body-only关联与两层close转换接缝。
- 计划冻结后分工：A查询，B新fixture/test，C独立只读复审；root独占解释器、测试、
  archive、验收和Git。所有作者FROZEN后才执行。

以下按实际发生顺序保留记录，不用后来的绿测覆盖首败。

## 原库存接缝首红

全部作者FROZEN后，root串行执行`original-inventory-counterexample`：4项均失败于
既有ProgramIndex没有`request_no_drive_paths`入口；不是fixture编译/结构错误。
四个原要求分别为原库存与own completion全槽、真实reject的helper N/R→host、
删附件守恒及budget1不空成功。它记录的是尚未实现的公开查询能力，不能冒充
已有查询返回了错误的native结论。

冻结源码900文件（原899加新测试），指纹`6f92ebaac79c02c3119b5cd74b77c0faf9f6c68021d1000dd41253b6e6e20597`
在运行前后相同。完整源码差异快照、命令、输出和JUnit保存在
`model_async_finished_requests/original-inventory-counterexample/`。随后才放行A/B写入。

## 写入期间的独立审查

- C/A发现首版测试的state分母只取interface.lifecycle，会漏掉context域并可能
  接受旧entry state。root在原同node改为host实际全部state Uses，并逐helper所选
  own N/R state槽到host核最新copy；原首红字节不覆盖。这是测试oracle修正。
- **Inferred（源码审查，待运行核实）**：`body_state_history`的native条件投影
  当前只处理await self；RequestAssociation own READ B到前一terminal的历史主体
  还没有动态条件投影桥。Observed True branch不填这个缺口。
  因此即使本批静态与实际call/terminal连接通过，也只验收这段子链，不能关闭
  F19第1项或整族；后续应核原R/Create/READ own ports及准确occurrence再接历史。

## 首轮联合与独立查询

- `first-joint-authored`：源码904文件指纹`9293ba30fe9971244b3c28977c2dd90fafeb6a666a6248d452a7203fef578682`
  前后稳定，rc2；1个collection error，因为pytest保留参数名`request`。尚未执行
  联合case，不能把这次错误说成模型拒绝。
- `initial-query-connected`：在同一904文件指纹上独立执行库存/真实reject ownN/R/
  全当前state/删附件/budget1四项，**4 PASS**，1.32秒pytest（非程序性能）。
- root另核新caller从RAISE landing继续时尚缺显式catch/context读写。作者已指出
  复用旧current-context模式的最薄修正；先保首版字节和collection失败，再修
  测试参数与这条真实状态连接。动态body-only历史桥及非finished内部继续开放。

## 当前同源验收

作者补齐两处caller catch/context READ_WRITE与后继Create/retry的最新版本连接，
修正pytest参数名后再次FROZEN。root串行`joint-current-context`：17 PASS，37.04秒；
随后只跑直接受影响的19模块`verified-current`：196 PASS，156.50秒（179旧/17新）。
两次均904稳定源文件、指纹
`ec1969fbdbcd2d52029ada1005886ad01620a9e77812f637fa835756f71f1969`。
未重跑前一门全部2104或全仓，旧tests/fixtures全部字节保持。

独立只读复审核全state/ownN-R/catch、原库存、预算和cycle，未发现本批结构阻断。
动态测试确认上述历史桥仍给expectedNone+准确主体gap；非finished native支路未展开。
这两个缺口使F19第1项及整族继续OPEN。详见验收报告，不以更多测试数代替原门。
