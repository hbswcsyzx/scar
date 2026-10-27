# PythonLiteral 表示与 payload budget 审查

**状态：Proposed 设计审查；没有修改产品代码，也没有运行测试或工作负载。**

## 范围与审查版本

- Worktree `/tmp/scar-structured-model-280qf4mi`，HEAD `13201ad24e0d8236623e28709f86e13a887ed4fb`；审查时工作树干净。
- 核对 `scar/ir/literals.py`、generic `record_codec`、v2 record validation/semantic decoder、SourceSemantics 与 optimization literal 调用点，以及现有 literal 测试。
- Python 官方 3.14 AST 页面当前解析为 3.14.8 文档；任务指定的目标运行环境是 3.14.7，报告只引用 3.14 语言/API 合同，不把文档 patch 版本冒充本机运行证据。

## 现有表示和缺口

`PythonLiteral` 当前有 `NONE/BOOL/INT/FLOAT64/STR/BYTES/TUPLE/ELLIPSIS`。`INT` 是规范十进制文本，`FLOAT64` 是 16 个小写十六进制字符，`BYTES` 是小写十六进制，只有 tuple 能有子项；它只验证当前对象的字段和子项类型，没有递归深度、展开节点数、总 payload、循环或共享 DAG 预算。[`literals.py:15-59`](../../../../../scar/ir/literals.py)

有四个路径需要共用同一个 literal 预检：

1. `from_python()` 递归 tuple，并用 `str(value)` 格式化整数；`to_python()` 递归 tuple，并用 `int(payload)` 解析整数；`as_dict()` 也递归展开。它们都没有容量边界。CPython 的十进制 `int`↔`str` 转换受 `sys.int_max_str_digits` 全局阈值限制，因此相同的 4,000 位对象会随宿主设置而成功或抛错；实现不能改 `sys.set_int_max_str_digits()` 来绕过这个限制。[`literals.py:61-103`](../../../../../scar/ir/literals.py)
2. `record_codec.encode/decode` 对 dataclass 字段递归遍历，完成对象构造后才调用 `record_errors`。环状对象可在检查前递归失败；输入 tuple/string/bytes 文本也可能在超预算后才被复制或解码。[`record_codec.py:43-73,76-146`](../../../../../scar/ir/record_codec.py)
3. `record_errors()` 先递归每个 dataclass 子字段，再调用 `__post_init__`；它不能单独保护 `PythonLiteral` 子树的循环和过深树。[`v2/_validation.py:70-130`](../../../../../scar/ir/v2/_validation.py)
4. v2 `_python_literal()` 目前先 `_record()` 深查 wire 子树，再递归构造 `PythonLiteral`；应在 `_record`/`_wire_type` 进入 literal 字段时就调用预算预检，而不能只修 `_python_literal` 最外层。[`v2/codec.py:215-241,345-351`](../../../../../scar/ir/v2/codec.py)

源语义前端对 `ast.Constant` 调 `PythonLiteral.from_python()`，转换失败保留 literal unsupported gap；另一套 `constants_v2._literal()` 手工调用 `PythonLiteral(kind, ...)` 并自己 `str(int)`，会绕过单一入口，应改走同一受限构造器。`ast.Constant.value` 的语言类型包含 complex，但当前 `PythonLiteral` 不包含；当前测试明确把 `1j` 当作 unsupported 用户类型。[`source_semantics_v2.py:197-205`](../../../../../scar/analysis/source_semantics_v2.py) [`local_statement_semantics_v2.py:291-297`](../../../../../scar/analysis/local_statement_semantics_v2.py) [`constants_v2.py:329-344`](../../../../../scar/analysis/constants_v2.py) [`test_semantics_schema_v2.py:61-92`](../../../../../tests/unit/test_semantics_schema_v2.py)

这里的 literal 是不可变值内容，不表示对象身份。Python list/dict/set、调用 `complex(...)` 和自定义类型仍是运行时构造/调用，不应因为增加 scalar 类型而变成 literal。AST 的 tuple 语法是 `ast.Tuple` 构造；它不等于 AST `Constant` 子树，前端仍需按 tuple construction 建模。[Python 3.14 `ast` 文档](https://docs.python.org/3.14/library/ast.html#ast.Constant)

## 建议的统一边界

建议使用一组不可由调用方扩大、在所有 API 中相同的上限：

| 预算 | 建议值 | 定义 |
|---|---:|---|
| 最大深度 | 64 | 根节点深度为 1；超限在递归/物化前拒绝。 |
| 最大展开节点 | 16,384 | 每个 literal 节点计一次；tuple item 边数最多 16,383。共享子树按每条展开路径重复计数，不做 identity 去重。 |
| 最大 aggregate scalar payload | 1,048,576 bytes | 对整棵 literal 求和；不含固定 JSON 字段名/tuple 结构开销。`str` 按 UTF-8 + `surrogatepass` 字节数，`bytes` 按原始字节数，`int` 按规范十进制字符数（含负号），float/complex 按 8/16 个二进制 payload 字节计。 |
| 最大整数十进制位数 | 4,096 digits | 不含可选负号；保留当前规范形式 (`0` 或无前导零整数，拒 `-0`)。 |
| 整数快速 bit 上界 | 13,608 bits | `10**4096 - 1` 的 bit length 上界。它只用于快速拒绝明显过大整数；`bit_length <= 13,608` 不能替代最终十进制位数检查。 |

上限应是实现常量而非 wire 字段或调用参数。节点/深度预算限制 Python 对象递归和结构开销；payload 预算阻止少量超长字符串/字节压过节点数预算。此处不是整个 JSON 文档字节数或解析 CPU 时间上限：`json.loads()` 在 literal 预检前已建立文档对象，若要限制完整 bundle 输入还需单独的 document/stream budget，不应把本门说成解决了它。

预算必须通过一个迭代 preflight 实现：维护显式 DFS 栈、当前路径上的 active identity set、深度和累计量；在入栈前计费并立即超限停止。只在 active 路径检测环，因此 forged cycle 会拒绝；不要对全局 seen 节点跳过重复 tuple 子树，因为共享 DAG 每次被引用都应计入展开预算。该流程须先检查精确类型/字段和长度，再跑 regex、`bytes.fromhex` 或 tuple/list 递归构造。

整数格式转换使用固定 base `10**9` 分块：wire 文本先做规范/位数长度检查，再由最多 9 位的片段构造整数；Python int 输出十进制时按 `divmod(n, 10**9)` 采集块并补齐低位块。转换中只让内建十进制转换处理不超过 9 位的小数段，不调用 `str(large_int)`/`int(large_decimal_string)`，不读写进程全局阈值。先用 `bit_length()` 快速拒绝远超 13,608 bits 的 Python int，再以分块实际输出字符数确认 4,096 位边界；4097 位数可能与 4096 位数落在同一 bit-length 桶中，不能只靠 bit bound。

## COMPLEX128 建议

若本阶段决定接入复杂数，新增精确类型 `LiteralKind.COMPLEX128`，保留 `{kind,payload,items}` 现有 wire 字段布局。`payload` 为 32 个小写十六进制字符：先 8 字节 big-endian IEEE-754 binary64 的 real component，再 8 字节的 imaginary component。`from_python` 仅接收 `type(value) is complex`；用打包的双精度分量编码，不经十进制、运算或 `repr`。`to_python` 解成两个 float 后构造 complex。complex 值仍只声明两个分量的内容，不能证明身份。

验收必须逐 component 比较 `struct.pack(">dd", restored.real, restored.imag)` 与原始 bytes，而不是用 complex `==`（NaN 不等于自身）。至少覆盖实部/虚部各自正负零、±inf、不同 quiet-NaN payload，tuple 内嵌 complex，以及一轮 record/v2 JSON 往返。如果目标环境会在 `complex(real, imag)` 过程中改变 signaling NaN 位型，要么明确只支持能保真的 binary64 范围并拒绝该编码，要么补有证据的精确构造路径；不要默称任意 NaN payload 已被验证。现有 float64 的位字符串格式保持原样。

AST 文档确认 `ast.Constant.value` 包括 complex；`1j` 可由新 scalar kind 表达。`-1j` 是 `UnaryOp`，`2+3j` 是 `BinOp`，`complex(1, 2)` 是 `Call`；本项只为真实 constant 值增加编码，不新增常量折叠器，也不将 call/binop 重标为 literal。[Python 3.14 `ast.Constant`](https://docs.python.org/3.14/library/ast.html#ast.Constant) [Python 3.14 数值类型](https://docs.python.org/3.14/library/stdtypes.html#numeric-types-int-float-complex)

## 调用入口和 schema 能力

建议在 `literals.py` 放唯一 budget 常量、迭代树预检、精确复杂数 codec 和受限构造/物化。`__post_init__` 做局部不变量与树级预检；`from_python` 先迭代扫描输入 exact builtins，再 bottom-up 构造；`to_python/as_dict/from_dict` 先完整预检后迭代转换。内部不要在每个子节点重复序列化其整棵子树。

`record_codec.encode/decode` 对 `PythonLiteral` 加专用 dispatch：encode 在 generic dataclass 递归前验证/迭代发出原 field layout；decode 对原始 wire dict 先 exact-field + budget scan，再构造。`record_errors` 遇见 `PythonLiteral` 时调用相同迭代预检而不先递归 child fields。v2 `_python_literal`、`_record/_wire_type` 以及 v2 SourceSemantics graph validation/to_dict 都须路由同一预检；不能只让一个 decoder 路径有限。

新增 enum member 本身会让当前 strict decoder 自动接受旧 graph schema 里的 COMPLEX128。因此 SourceSemantics v2/OIR 当前 schema 不应默默获得新能力：可选择在旧 family validator/decoder 显式拒绝该 kind 并让前端保留原 unsupported gap，或通过经批准的 capability/schema 版本迁移后只在新版本写出。Program graph 是不同 wire family：若要在 core graph 中表示复杂数，应在计划的 program schema v16 显式增加对应类型能力，旧 v1–v15 reader/writer 与原 bytes 保持不变。`LiteralOrigin` 当前是独立 core 值类型 (`bool|int|float|str|None`)，不能因共享 `PythonLiteral` 扩展就隐式放宽。

Program graph codec 当前 `ensure_ascii=False`，而 SourceSemantics `to_json()` 是 `ensure_ascii=True`。[`program/codec.py:240-241`](../../../../../scar/ir/program/codec.py) [`semantics_v2.py:580-582`](../../../../../scar/ir/semantics_v2.py) SourceSemantics 已有孤立 surrogate 往返测试；Program JSON text 若带孤立 surrogate，后续严格 `.encode("utf-8")` 不能直接编码。若要求 Program snapshot/UTF-8 artifact 无损且旧普通 Unicode wire bytes 不变，建议只对 surrogate code points 采用 JSON `\uXXXX` escaping、普通非 ASCII 字符维持现输出；至少分别测孤立 high/low surrogate 的 dump→UTF-8 encode→load 精确 code point 往返和一个普通非 ASCII golden bytes 不变。不要把全局 `ensure_ascii=True` 当兼容修复，因为它会改普通非 ASCII 的既有 wire bytes。连续 surrogate-pair code points 是否需保留为两个 Python code points 应在 API 合同中另行明确；不能未经验证声称 JSON decoder 会保留该形态。

## 最小验收矩阵

1. 所有既有 literal 值/float 位模式原测试继续通过；旧 schema 文件原 bytes 与旧字段保持不变。
2. COMPLEX128 上述 component-bit 矩阵经 `from_python → as_dict/from_dict → record_codec → v2` 往返；不支持的 complex 构造表达仍保持 Call/BinOp gap/结构。
3. 深度 64/65、展开节点 16,384/16,385、payload 1MiB/超 1 byte、int 4,096/4,097 位逐界测试；正界成功、越界在产生子结构前失败。
4. 重复共享子树按展开次数计费；主动 `object.__setattr__` 构造的环在 constructor-checked APIs、encode/decode validator 上以受控错误拒绝，不冒 `RecursionError`。
5. 降低 CPython `int_max_str_digits` 的隔离子进程中，4,096 位 int literal 仍可 encode/decode/to_python；调用后全局阈值不变；4,097 位拒绝。不能用修改进程设置的测试“通过”。
6. 正常 `str/bytes` 的 payload 边界、孤立 high/low surrogate、旧 Program 非 ASCII wire golden；generic codec、v2 `_python_literal`、SourceSemantics graph 和新 Program capability 都走同一 literal budget。
7. schema2/旧 OIR 对新 kind 的拒绝或新 capability revision 的严格接收与旧 revision reader 分开验证；不能靠仅更新 `LiteralKind` 就扩大老格式语言。

## 复用点与有限范围

可复用现有 field shape、canonical float64/bytes/decimal payload、严格 JSON duplicate-key 检测、`record_codec` 的 exact field/tag 检查和 source frontend 的 unsupported literal gap。需要新增的只是统一 literal 预检/迭代转换与明确的 COMPLEX128 capability gate；不需要新的 parser、任意对象编码或 runtime identity 检测。

审查时源 SHA-256：

| 文件 | SHA-256 |
|---|---|
| `scar/ir/literals.py` | `3e1c8e95c1a32e8454007f0b8c35e3724028732d376a5550ca1c5d6e7ce949d3` |
| `scar/ir/record_codec.py` | `2facc7de22eadf2c095181a6f258ecbb7a529079d5c92b6414bbb0a0968ec6c4` |
| `scar/ir/v2/_validation.py` | `b4ae9ee13f65fedc7e614770784ceebfef6806cb042a1f42b4d585f3ecb64085` |
| `scar/ir/v2/codec.py` | `511daa3a5d1ee89ae7f7c545dd5f7161ea3a3a6c9f3c1b01b4224c0ba751fcc1` |
| `scar/ir/semantics_v2.py` | `f938bc3635b50e2a4a1efe29b5e364f82ff274931bd2f857beab71e93969a9a2` |
| `scar/ir/v2/optimization.py` | `4e981786c52d9bbc50cb76f8b469153d035692daed2c2941e27b3e7fea8dcdc5` |
| `scar/analysis/source_semantics_v2.py` | `4d81202f298142b766034d2907262d05cd44d40a825ff54a0c4609f1702dece8` |
| `scar/analysis/local_statement_semantics_v2.py` | `5ab90e2c93dbfdb0876971d1ff23c2209ec2211054f0a7f600881481e39003c5` |
| `scar/analysis/constants_v2.py` | `00295d01d9eac66382a6120c488845e284289fa1ab97d8e3b27595957f32607c` |
| `tests/unit/test_semantics_schema_v2.py` | `24305603d3d4348cff2e7cf80499720dd1fc6a62193260e8a80cf6badcefca03` |
| `tests/unit/test_static_optimization_v2.py` | `dea2f65bb7b5dee32400c377505373eee4ec6e8911415b2f42f8ee17e036ae70` |

Official references: [Python 3.14 AST constants](https://docs.python.org/3.14/library/ast.html#ast.Constant), [built-in numeric types](https://docs.python.org/3.14/library/stdtypes.html#numeric-types-int-float-complex), [integer string conversion limits](https://docs.python.org/3.14/library/stdtypes.html#integer-string-conversion-length-limitation), [sys integer limit controls](https://docs.python.org/3.14/library/sys.html#sys.set_int_max_str_digits), [JSON escaping and surrogate behavior](https://docs.python.org/3.14/library/json.html#character-encodings).
