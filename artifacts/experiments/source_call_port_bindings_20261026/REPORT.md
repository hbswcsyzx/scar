# Source call ports：真实首次产出

2026-10-26。candidate04实际session28466 exit1：源端口组件已完成，随后实验审计脚本字段错误退出；原窗口保持失败。

同一次正常 fresh linker读取100438 entries/exits、100550 attempts，生产2516个有条件调用绑定、6805个原caller Use/Value→formal slot/value端口。其余98034 attempts保留具体issue：96481 HANDSHAKE、1386 SOURCE_CORE、167 DISPATCH。端点均带原body artifact/namespace/Region，引用原CodeSourceLink、CallSiteLink及actual attempt/handshake/entry。没有新造IR节点、动态identity或CallActivation。

模型stored6605220B / decoded99622812B；准确receipt见FIRST_DELIVERY.json。完整strict正常reader读回通过，同fresh会话重算的call-source/slot/caller/arity四个真实换置反例均拒绝。manifest在模型关闭、读回和反例完成后落盘。

原fresh路由进度记录：argument_routes27、completion_routes27、InvocationReturn6402、issues100523；原wire及默认规则未改。旧27逐项映射审计尚待独立postflight，不能凭计数宣称逐项相同。返回→result只复用原窄DIRECT_NORMAL_COMPLETION_V1，不据新argument绑定为所有2516调用补return资格。

失败是port_consumer.compare_legacy写成routing.arguments/completions，真实类型字段为argument_routes/completion_routes。4生产源码无此访问，producer及同session consumer已完成。GNU-time39:34.74，worker2365.628577s，RSS2323504KiB；read-only CodeWitness20loads/242matches/compile attempts0/source bytes read0。failure、原3次缺件失败及其freeze全部保留，不重跑完整factory。

本产物是静态源语言端口与实际entry的有条件对应；引用/内容/state/world效果/ready、whole-program完整性和转换许可均未授予。原source858/6882正式指针不变。
