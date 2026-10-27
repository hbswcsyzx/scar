# 下一批 owner / selector / literal：最小分工建议

状态：**Proposed，仅只读设计审查，不计任何门完成**。依据冻结 P1 `79bf2a9` 后的
WHOLE_PROGRAM_MODEL §3–4、FIRST_STAGE_COMPLETION_MATRIX、PYTHON314_PROTOCOL_CATALOG、
数据协议 §7/11，以及现 program/model.py、validation.py、v2/values.py/correspondence.py。
未改 tracked 文件，未运行测试、采集、workload 或解释目标程序。

## 1. 已有事实及缺口

- StateLocation 只有 id/label/extent/stability；label 不能提供机器可查的 owner/domain。
- StateAccess 已有 reference/before/after/footprint；ReferenceValue 已有 targets/selector。
  它们是唯一规范访问及状态边，不能再造平行 read/write 或 def-use 表。
- Footprint 的 WHOLE/INTERVAL/UNKNOWN 可保留，但目前没有区间单位；没有 key/field/
  动态 index 到实际访问及粗细 location 覆盖的连接。不同 ID 不证明 disjoint。
- LiteralOrigin 只支持 None/bool/int/有限 float/str；bytes/complex/Ellipsis 与非有限数值
  尚不能精确表达。容器构造已有协议，不能用扩充 literal 来绕过构造效果。
- v2 allocation/region/materialization、逻辑版本、provenance 可保留；SLOT_VERSION
  correspondence 不足以替代带 activation/iteration 的 ValueOccurrence→Denotation。

## 2. 只补以下规范连接，不建立新解释器

**A．Location 声明与 owner 绑定。** 为既有 LocationID 增加可查询的 domain、owner
要求、footprint 单位和有效静态 scope。owner 是引用/资源等规范身份接口，不能是
label、变量名、裸地址或 StorageAllocationID 的同义词。实际访问的对象 owner 直接
复用 `StateAccess.reference` 所指的本操作 Reference Use；资源 owner 复用现
ResourceLocation。需要约束 owner 来自哪个入口或协议结果时引用已有 ValueID/端口，
不另存实际 object。区分“声明依赖的 owner 端口”与“本次访问绑定的 owner”。
静态 Location 可是保守抽象域；若声明为实例位置模板，必须说明按何种 owner/
activation 实例化，不能让同一静态 ValueID 在不同调用/迭代中指向同一动态对象。

**B．Selector 与精化关系。** 用 `(OperationID, accesses 的下标)` 附着访问说明：
selector 的原生协议事实、静态 literal key 或本操作已有 ordered UseID。所有动态
owner/key/step 的求值依赖必须在原 uses 中存在并支配访问；不得在说明表重新求值。
静态 attribute 名只是协议参数；只有已解析实现才能将 lookup 精化成字段读取。
已有 footprint 仍是规范几何摘要；精化说明应说明单位/相对 owner、与该摘要的兼容性，
不再保存第二份 before/after。补显式 scoped covers/overlaps/disjoint 声明及依据；
未证关系保守冲突，不能从 key 字符串不同或 world 名字不同推出不相交。
当前 core 的 READ 不产生后态、STATE_ORDER 不等于通用内存栅栏；跨 coarse/fine 的
RAW/WAR/WAW 顺序与状态一致性必须有明确组合规则，缺口不能只靠关系表声称解决。
本批仅验声明/连接良构；运行 owner/lifetime、关系真实性和完整失效仍是后续义务。

**C．Literal 的无损内容描述。** 只扩一处 canonical literal 内容编码，沿用既有
LiteralOrigin→Value→Use 路线。精确 tag 区分 bool/int；整数保留任意精度；float 用
明确格式的 binary64 位编码，complex 保存两分量位编码，bytes 用可逆 bytes 编码，
None/Ellipsis 用独立 tag；不能经普通 JSON number 抹掉 -0、NaN/Inf 或 NaN payload。
这是内容/类型描述，不增加对象 identity、无效果或跨执行不变证明。编译折叠得到的
tuple/frozenset 等先引用原生 compiler/provider 常量事实并显式保留未映射边界，
不把普通 List/Tuple/Dict/Set AST 的运行构造改称常量；完整常量覆盖仍单独列缺口。

## 3. 可直接复用与实现分工

- **owner/selector 组：** 先冻结上述声明及已有 access 的连接不变量；复用 StateAccess、
  ReferenceValue、环境入口、ResourceLocation、state SSA 和 validator 的 owner/dominance。
  不把完整细粒度 alias 分析器作为本批前提；未解析域保留具体保守边界。
- **literal 组：** 复用 ast/tokenize 的源码常量事实、symtable 的作用域和 compile/dis
  的版本化编译见证；只用 struct/base64 等标准编码处理内容，不写 eval/对象执行器。
  新 wire capability 必须保留旧 LiteralOrigin 解码及非有限值严格往返规则。
- **连接审查组：** 复用 native/provider facts、既有 Uses/query/codec；检查端口/访问
  下标、作用域与缺失/冲突，不解释 TreeSpec、不复制调用 actuals、不造新 producer 表。
- v2 StorageRegion 的 offset/shape/strides/dtype 描述真实物理几何；copy/deepcopy/cast
  的逻辑关系必须另接实际协议及输入状态，不能由同 allocation/shape/采样推断。
  参数和值只保存所需 metadata/来源；不逐轮保存 Tensor 内容。

## 4. 三个最危险的可验收反例（本轮未执行）

1. **owner/selector 的动态性与协议效果：** 同一静态 `obj[key]` 在两次 activation
   绑定不同 owner；另有 `d[True]` 与 `d[1]` 指同一 dict entry，自定义 `__getitem__`
   还可修改别处后 raise。不能按 ValueID/key 类型或文本判 identity/disjoint；应保留
   owner/key Uses、lookup boundary、冲突与部分后态。精确已证 builtin 非重叠例才可精化。
2. **共享写与副本：** `torch.from_numpy(a)` 后 NumPy 原位写，Torch `_version` 可不变；
   `clone()` 内容初始相同却是另一可写物化，view 则可共享写。前者必须触发外部可变域的
   版本/失效义务，后两者不得只靠 storage 或采样决定逻辑相同/可共享；地址重用需代次。
3. **表示中的“常量”与源程序证明：** Export/TreeSpec 的某个常量叶、一次 observed
   返回值、compiled co_consts 项，都不证明原 `import; lookup; compute` 子图可删除。
   必须保留原输入/环境/状态/完成及活外部效果；-0/complex/bytes/Ellipsis 必须无损，
   精确 literal 内容也不授权 interning/identity/输出 alias 改变。

建议顺序：先冻结 A/B 的静态含义及 C 编码→各自小型结构反例→独立连接/legacy 回归。
本建议不包含 source lowering、动态 instance 采集、优化规则或 backend。
