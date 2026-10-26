真实 functools.py:553–598（原 V7 Lambda 前沿）已完整恢复：actual exit0 / 79.099919s，170 ops，普通 STRUCTURE 与独立 source/readonly CodeWitness 均 PASS，1 load / 2 complete matches / compile0。原 243/817/100438 分母保留；只新增1个成功原候选（历史调用权重1），45个最新保存 unsupported→44，未加当前runtime。

图内两个真实 Region：outer body + 原 :587 Lambda expression body（17ops）。原 SG declaration/call_time FUNCTION、$return、词法scope和原 parent code co_consts[1] 复用；Lambda.body 直接求值两个cell内容→Dict→真实NORMAL payload/world Use，未合成FunctionDef/Return AST，未冒称旧control suite。BODY_QUERY.json保实际原ID/typed interface/capture/return Uses。创建不执行child；未来调用仍须原code/default/frame/arguments等BindingCondition成立。

MAKE_LAMBDA_FUNCTION只有一个函数payload。globals/cells捕获原输入Use；builtins/defaults/kwdefaults仅是原创建的typed initialized-field摘要，child环境形参保持独立。没有target字段读取op、没有额外Observed factory结果、没有冻结cell内容或证明后续defaults不变。source overlay V2显式携带LambdaBodyDefinition；正常V1 encode/decode保旧字段/字节，不增加空lambda_bodies。由已存旧Set language小记录验证V1往返一致，未重lower旧body。

本次独立 expression adapter支持Name、旧精确scalar Constant、普通Dict、固定Call、Attribute、简单Subscript；其它child语法/嵌套cell/展开/增量Dict等保精确前沿。源内defaults只在创建时按源顺序求值，child body不作为outer执行。首轮31.578392s FAILED保留：原V7 tuple子Name旧overlay是OPAQUE，现cell store有精确NORMAL结果；env guard现只在UNPACK_TARGETS cap+原child source+exact NORMAL[i] RHS成立时接受该原记录，不改旧opcode、不放宽其它Name guard。随后同entry fresh正常读回成功。

12源窄diff以f4cadb9c为前像。三独立模块是lowerer、validator与typed source接口；共享hooks另列，main的constant/shared-context/worker改动须语义窄合。V8联合CODE_CONSTANTS选择见V8_HANDOFF.md，parent Try独立出口ABI的一行必要修正也明确列出并实施（本门之后，组合未实测），本门未授组合资格。

交付不复制31.85MB source context或原SP5；正常gate后仅一次body-only codec/ProgramIndex查询、无源context重验证。该查询曾读压缩文件两遍，累计7,508,070B；解码31,853,405B，IO澄清单独保存，原receipt不倒改。累计所有I/O仍OPEN。raw/compile/target/publication/currentRun binding皆0，不恢复已退出live owner，不称第一阶段完整。

Root审后两处兼容收口不重跑大门：旧V1 lowered-return两处writer改用同一encode helper，防空新字段漏入旧metadata；FunctionTry只重写自己root Region的packet出口，保child独立ABI。两文件前/后/actual-run SHA分列，其余Lambda producer/reader与本次真实输入一致。

主线集成说明：从58be6108按12个生产源窄合，保留主线CodeConstant能力和既有context/body分离。
V8另外按原definition-time AST自动选择CODE_CONSTANTS；Lambda defaults在创建帧、body在独立Region。
FunctionTry的RAISE ABI后处理现已限定创建函数自己的Region，不重写独立child。该组合未新跑，
不追认79.0999s原实测覆盖了后续修改。最终普通main reader结果另存lambda_main_consumer产物。

计数更正：原worker的170是creating-frame construction_operations计数，child的17个操作
漏计了该预算字段；完整规范图实际为187个操作。原metadata的187条operation-source link、
两Region及child17操作一致；原170收据保留，不能再把它当作完整graph操作数。
main普通read_structure已正常返回；外层脚本错误断言len(graph.operations)==170导致exit1，
该失败保留，不将整个wrapper记PASS。main另将child emit改为直接使用owner的基础emit，
共享预算且绕过父Try scope；不增加或改变已有操作/ID。该预算修正未重跑大源lower。
