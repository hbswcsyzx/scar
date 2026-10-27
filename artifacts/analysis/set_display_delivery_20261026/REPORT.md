已完成通用 Set display 与现有 local AugAssign 的自动入口接线。原 49 个最新 UNSUPPORTED 首前沿：fixed unpack 7/85 历史调用、With 旧前沿 7/17、Set 6/75、generator 旧前沿 5/142、AugAssign 5/54、comprehension 4/77；其余 15 项分散。旧前沿没有因新 cap 存在而自动改成功。

本轮实际普通 lower→STRUCTURE→独立 source/readonly CodeWitness 均通过：

| 原源码入口 | ops | 历史调用权重 |
|---|---:|---:|
| typing.py:3839 | 240 | 62 |
| typing.py:1985 | 235 | 8 |
| torch/nn/modules/container.py:361 | 65 | 1 |

Set 两项按全部 6 个同原因前沿的原调用权重排序自动选前 2；同 file 一次 prepare，整个成功 worker 313.033697s，readonly 1 load / 4 matches / compile 0。首轮 2 FAILED/69.590759s 是新 source-linked Set 协议遗漏 environment validator 接线；原错误、收据和程序目录保留，补精确 cap/原 SG Set/output/opcode 分支后 fresh 成功，未放松通用 guard。

Set 复用原 Opcode.BUILD_SET，仅一个 incomplete allocation/hash/equality world 接口，按源顺序保元素 Use/held references，NORMAL/RAISE 均消费这些输入；hash/equality、去重、partial cleanup、finalizers 不当纯运算。参考合同为 [CPython 3.14 BUILD_SET](https://github.com/python/cpython/blob/v3.14.0/Python/bytecodes.c#L1854-L1878)，不是执行时解释器字节证明。非 starred、≤30 普通元素；star/incremental 与 comprehension 保具体前沿。输出对象内容/同一性/完整副作用仍未证明。

5 个 AugAssign 原 target 中 4 个是普通 local Name、1 个是 Attribute；4 Name 的历史权重 25/2/1/1，未全部重试。V6 按 AST AugAssign 启用已存在 FUNCTION_TRY/augmented_assignment；未改 Try、in-place 或 heap 实现。按普通 local 原函数 AST 节点数最小选 1，65.312353s，readonly 1 load / 2 matches / compile 0 完整通过；heap 仍 unsupported。Set 成功以后只追加这一 worklist 选择条件，其余 Set producer/reader 源码不变，两个实际版本 SHA 分列。

V6 自动选择 Set 和现有 AugAssign，SOURCE_ENTRY_PROFILES/LATEST 常量导出；旧 None/V2–V5 行为/wire 不变。3 个原 SP5 七字段见 delta3，不重复存大 source context。原 243/817/100438 分母保留，最新保存 UNSUPPORTED 49→46，历史权重 71 不计为当前 Run 新绑定。raw/compile/target/publication/current binding 皆 0；累计 I/O 未全计费保 OPEN。至此收口，不再扩语法/矩阵。
