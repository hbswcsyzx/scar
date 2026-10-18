# Python literal 表示审查

**基线**：worktree `/tmp/scar-structured-model-280qf4mi`，HEAD `78dbac3dcd7a303d84ce645a68f52a6a4cf8f1a2`。本报告只做只读审查和短小标准库探针；没有改产品/测试、运行 SCAR 测试、执行样例源码或跑 workload。

## 结论

当前 core `LiteralOrigin` 只完整表达 `None`、精确 `bool` / `int` / `str` 和有限 `float` 的 Python 值。它不是完整 Python literal 编码，也不承载 source/compile phase 或对象身份。另有可复用的 `scar.ir.literals.PythonLiteral`：它精确保留 `None`、bool、int、float64 位型、str、bytes、递归 tuple、Ellipsis，但没有 complex；它现用于 v2 semantic/optimization 记录，没有接入 `ProgramGraph`。

因此第一阶段 literal 分母仍未关闭。最小下一门应复用 typed payload 记录而不是扩大裸 JSON union；增加 complex 的精确载荷和有界校验，在 core 中按新 wire capability 接入，同时分开 payload、来源阶段、运行对象身份。list/dict/set 仍是有序构造操作，不能编码成 literal。编译器将表达式放进 `co_consts` 不是 AST literal 的同义词。

## Observed：当前仓库的支持范围

- [`model.py`](../../../../scar/ir/program/model.py) `LiteralOrigin` 只接收 `bool | int | float | str | None`；`bool/int/str` 要求精确 builtin type，float 必须 `math.isfinite`。`DataValue` 再按 exact Python type 检查 `data_type`；`ReferenceValue` 可持有 literal，但强制 identity 未知、targets 为空、selector 为 `UNKNOWN`。`StateVersionValue`、local binding 和 protocol token 不能以 `LiteralOrigin` 定义。
- [`program_inventory.py`](../../../../scar/analysis/program_inventory.py) 用 `LiteralOrigin(node.value)` 判 AST `Constant` 是否在 core 标量子集内；bytes、complex、Ellipsis 和溢出成 infinity 的 float 都会被标成 representation gap。[`structured_lowering.py`](../../../../scar/analysis/structured_lowering.py) 的常量 lowering 同样建 literal `ReferenceValue`，保持身份未知。tuple/list 是 AST 表达式，经普通 source-operation / `INVOKE` 路径连接并留下动态语义 gap；它们不是 `LiteralOrigin`。dict/set 在该 structured body 子集尚未连接。
- [`program.codec`](../../../../scar/ir/program/codec.py) 的 wire schema 当前为 v14，literal 没有单独 capability。通用 [`record_codec.py`](../../../../scar/ir/record_codec.py) 将标量嵌入 `LiteralOrigin.value` 并交给严格 JSON；它显式拒绝非有限 float，JSON dumps 也 `allow_nan=False`。bytes、complex、tuple、Ellipsis 不符合该字段类型/编码。core 目前不会把它们静默写成字符串。
- 已有共享编码方案在 [`literals.py`](../../../../scar/ir/literals.py)：`PythonLiteral` 的 kind 是 `NONE/BOOL/INT/FLOAT64/STR/BYTES/TUPLE/ELLIPSIS`；int 用 canonical decimal string，bytes 用小写 hex，float 用 16 位大端 IEEE-754 hex，tuple 递归保存。它保存 signed zero 和 NaN 的位型，不自证对象 identity；没有 COMPLEX kind。v2 codec 的 `_python_literal` 精确要求 `kind/payload/items` 三字段并递归解码。v2 `source_semantics_v2` 会把 AST `Constant` 转成 `PythonLiteral`，超出它的子集则留下 gap；这是另一个语义层，不表示 core codec 已支持。
- 构造语义分册 [`PYTHON_DATA_DEFINITION_PROTOCOLS.md`](../../../../docs/model/PYTHON_DATA_DEFINITION_PROTOCOLS.md) 与分母 [`FIRST_STAGE_COMPLETION_MATRIX.md`](../../../../docs/FIRST_STAGE_COMPLETION_MATRIX.md) 已明确列出 bytes/complex/Ellipsis、非有限数值、identity/编译折叠/运行构造是未完成项。这里的代码核对与该分母一致。

## Observed：CPython 3.14.7 轻量见证

`literals_probe.py` 对固定的 15 条短赋值使用 `ast.parse`, `compile(..., optimize=0)` 和 `dis.get_instructions`；只编译，不调用 `exec`。输出在 `literals_probe.json`。证据包括：

- `None/bool/int/float/bytes/complex/Ellipsis` 是 AST `Constant`；`1j` 的 value 是 complex。`1e309` 已成为 float infinity。core 只接受其中有限的部分。
- `-0.0` 在 AST 中是 `UnaryOp(USub, Constant(0.0))`，编译后的 `co_consts` 有 `8000000000000000` 负零位型。
- `1 + 2j` 在 AST 中仍是 `BinOp`，但这个 Python 版本的编译结果含 complex `co_consts`，指令只加载编译常量。来源语法和 code-object 常量池不是同一事实。
- `(1, 2)` 是 AST `Tuple`，编译结果含 tuple constant；`[1, 2]`、`{'a': 1}`、`{1, 2}` 的普通赋值分别保留 `BUILD_LIST`、`BUILD_MAP`、`BUILD_SET`。在 `item in {1, 2}` 中，AST 仍是 `Set`，但编译器把成员集合放入 frozenset `co_consts`。不能用 `co_consts` 值反推所有语法构造都是可替换 literal。

这是本机 CPython 3.14.7 的编译观察，不代表其他 Python 实现或版本具有相同常量折叠，也未观察对象跨调用 identity。

## Inferred：完整模型还缺什么

1. **精确值和 Python 类型标签必须同存。** 当前 `LiteralOrigin` 裸 scalar 的 Python dataclass equality 会沿用 `True == 1` 和 `-0.0 == 0.0`；即使 `DataValue.data_type` 另外区分 bool/int，也不能把 origin 相等当作 typed literal 相等或 identity。`PythonLiteral.kind` 是现成的显式区分。
2. **float/complex 需位型定义而非只按数值比较。** core 拒绝 infinity/NaN，且没有明确的 bitwise payload。PythonLiteral 的 IEEE hex 已解决 float 的 signed-zero/NaN 表示；complex 可增加两组 float64 位型。负零见证证明只记录数值相等不足以复原所有浮点观察。
3. **源常量、编译常量、运行时构造是不同来源。** `LiteralOrigin` 只有 `value`，没有 AST 定义位置、code-object/`co_consts` 槽或编译器版本。tuple/complex 优化见证说明不能因某个 `co_consts` 项就删除原操作/外围 effect，也不能凭 AST 常量 spelling 推断 CPython 对象池别名。
4. **值相等不代表对象身份相同。** `ReferenceValue` 的 literal 形状刻意把 identity 设为未知，这是安全边界；但模型无法表达已知 singleton identity、同一 code constant 的共享 identity，亦不能推导不同字面值对象是新鲜分配。要保留 `is`/alias 观察，identity 需要独立 typed、run/code-scope 的关系；不允许用相同 payload、ValueID 或 literal hash 代替。
5. **容器构造保持为 operation。** list/dict/set 有分配；set/dict 还涉及 hash/equality、展开、异常或部分副作用。tuple 不可变，但编译时可能复用 `co_consts`，runtime identity 仍可能被观察。容器 payload 可用于静态值评估/证明，不能把创建/构造 operation 抹掉。
6. **资源预算需要进 canonical contract。** `PythonLiteral` 递归 tuple 和 `INT` 的十进制转换目前没有此类 record 的统一 depth/item/byte/bit budget；`from_python`/`to_python` 走 `str(int)`/`int(str)`，极大整数还受运行环境的十进制转换限制。即使复用它，也要为 wire parser、嵌套 tuple、payload 总量定义固定预算及超预算 gap，不能无界递归或悄悄截断。

## Proposed：最小独立 literal gate

- 将 `PythonLiteral` 用作 typed payload 的起点；加 `COMPLEX128`（实部/虚部分别使用 canonical 16-hex IEEE-754 binary64 bits），并覆盖所有合法 scalar payload：`None/bool/int/float/complex/str/bytes/Ellipsis`。tuple 仅作为 immutable `PythonLiteral` 的递归 payload，不将 list/dict/set 加入 literal union。
- 将其接到新版本 ProgramGraph literal-origin wire；旧 v1–v14 标量 encoding 保持精确兼容，旧 schema 不得接受新 typed payload。对新的 typed literal 保存 kind discriminator、exact payload、严格嵌套与大小预算。超预算保留明确 gap/unsupported literal，不退回 `str(value)`。
- `DataValue` 的 type 由 exact kind 推导/验证；literal `ReferenceValue` 仍不默认给身份。`None/bool/Ellipsis` 的语言 singleton、字符串/bytes/tuple 常量池、编译期折叠分别作为 identity/provenance 规则，不混进 payload 相等逻辑；如果当前模型没有相应作用域证据，则在 identity 观察上保持 unknown。
- Source AST `Constant`、编译 code-object `co_consts` 项、常规容器/格式化字符串构造使用不同 producer/source relation。M1 只需清晰表达和反例；M3/M4 才负责将源/编译 witness/运行 occurrence 对应到这些记录，不能把自动 bytecode 前端设成 M1 的前提。

### 建议的有限验收

正例：精确 roundtrip bool/int 区别、空/嵌套 tuple、任意 bytes、Ellipsis、`+0.0/-0.0`、inf/NaN 位型、complex 两分量；新版 wire 严格重放并受预算控制。负例：误把 bool 当 int、错误 kind/hex/tuple payload、超深/超大 payload、旧 schema 携带新 typed literal、字典/list/set 报成 LiteralOrigin、相等 literal 被当作同一 object、source tuple 构造被无 producer 地换成 code constant。

这个 gate 只关闭 literal 类型与来源边界，不关闭 owner/selector、完整 source lowering、编译/runtime identity 对应或 M0–M2 全模型。

## Probe reproduction and provenance

Command (environment `lewm`; Python 3.14.7; no target code execution):

```sh
source /home/zyf/miniconda3/etc/profile.d/conda.sh && conda activate lewm && PYTHONDONTWRITEBYTECODE=1 python artifacts/experiments/b1_call_operands/model_state_locations/design/literals_probe.py > artifacts/experiments/b1_call_operands/model_state_locations/design/literals_probe.json
```

Probe script SHA-256: `7e7855e76078c2061a52e120a1ac472adbdbb8293c9f41cca34f8f8f30fb7faa`; output SHA-256: `c8aa29aec97fd42bf6f8950bc43b823c252c0b394b6ce39b10c73e8021be1568`.

## Read-source fingerprints

All hashes below were read at the baseline HEAD above.

| File | SHA-256 |
| --- | --- |
| `docs/FIRST_STAGE_COMPLETION_MATRIX.md` | `2067ce9b9c475b3f98e02fc8151d92f0606778d47279f69f0e082d75eb14a7d8` |
| `docs/WHOLE_PROGRAM_MODEL.md` | `ea4bb6cd1d4976ad7e6d1b7ccd214c5cdeafa0f657623e2363fd110bada9e509` |
| `docs/WHOLE_PROGRAM_MODEL_PLAN.md` | `eedc5f812b364080b6ce6b751563756beff1d54c2eb2ac01186fd458c0c5e841` |
| `docs/PYTHON314_PROTOCOL_CATALOG.md` | `197af927c2de04a5a424b2e3f480d00c17c7b2a23c676ac86baebb7b441fc6bd` |
| `docs/model/PYTHON_DATA_DEFINITION_PROTOCOLS.md` | `1a5f87dce26236a97e41ad24e0085ec2d73a634b9ce0bd709ce9fc693100fb4a` |
| `scar/ir/program/model.py` | `3a72c7692afdb19f74f19df5990527140e360748954c64dde3e335551580b2b1` |
| `scar/ir/program/validation.py` | `04ed471b6164b14e738ed0c22aee16f256f2a925038321a478834ef68aff7264` |
| `scar/ir/program/codec.py` | `415cd3c7832e00c5ffb9ae7332802514944c98b672136a0d010c640d0c9acec0` |
| `scar/ir/record_codec.py` | `2facc7de22eadf2c095181a6f258ecbb7a529079d5c92b6414bbb0a0968ec6c4` |
| `scar/ir/literals.py` | `3e1c8e95c1a32e8454007f0b8c35e3724028732d376a5550ca1c5d6e7ce949d3` |
| `scar/ir/v2/codec.py` | `511daa3a5d1ee89ae7f7c545dd5f7161ea3a3a6c9f3c1b01b4224c0ba751fcc1` |
| `scar/ir/v2/semantic.py` | `9d0af8a2b4a868df00388ccb910cdabdc93066aad7ff0e593d1c8d0e969885ab` |
| `scar/analysis/program_inventory.py` | `f22ffebf03f6f255e26b7d60f20dff73f4bebdf68362a30800e9ef08c771d634` |
| `scar/analysis/program_lowering.py` | `5ab3f166d4f949fe3efa0905dfacc39657562cf3dc0bc96bb1193c1a94b75068` |
| `scar/analysis/structured_lowering.py` | `2e15e5c3586523507d164152f367e39ae6db9436c312273f3943bc1438688969` |
| `scar/analysis/source_semantics_v2.py` | `4d81202f298142b766034d2907262d05cd44d40a825ff54a0c4609f1702dece8` |
| `scar/analysis/local_statement_semantics_v2.py` | `5ab90e2c93dbfdb0876971d1ff23c2209ec2211054f0a7f600881481e39003c5` |
