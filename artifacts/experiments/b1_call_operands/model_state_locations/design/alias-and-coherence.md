# M1 owner / selector / alias / coherence 独立设计审查

基线：`78dbac3dcd7a303d84ce645a68f52a6a4cf8f1a2`。状态：**Proposed；仅源码/主源文档审查，未实施、未运行测试或采集**。没有修改产品、测试、环境或旧证据。

## 1. 明确决策：保留根状态 SSA，细地址不是第二套 field SSA

本门推荐直接冻结此方案：**StateLocation 是 coherence root；owner + selector 细分原 StateAccess 的地址，不另外生成字段状态版本。**

```text
原 Operation / Use(owner,key,index,...) + 当前 StateVersion(root)
                ↓ 原 StateAccess（可带 typed address）
         read result / root 的原 after
```

同 root 内所有写都推进该 root 的规范版本。细读也必须消费当前 root，不因 owner/字段名字不同而继续使用旧版本。这样 coarse write→fine read 与 fine write→coarse read 两个方向都由现有 SSA 接上，不留待未来补 coherence。

若未来需要独立 field SSA，必须有完整的 root/field 投影、重建及所有已知/未知写的同步更新规则；仅加 parent/alias 边而让两套 SSA 独立前进不够。本门**不采用**该方案。

多个 coherence roots 可以存在，但其分离必须是有条件的域接口约定，不能由不同 LocationID、label 或不同 owner 推导。已知可能重叠的旧细 locations：保留 legacy 解码，但不得因新增地址接口授予独立有效性；新模型应归并到同根，或显式让每条实际完成路径更新全部受影响根。未知 native/callback 写不能跳过任何其可能影响的根。

## 2. Observed：当前代码实际具有什么

| 现有结构与位置 | 已能表达/校验 | 不能由它推导 |
| --- | --- | --- |
| `program/model.py:107–155` Footprint / StateLocation | WHOLE、非负半开 INTERVAL、UNKNOWN；extent、INTERNAL/EXTERNAL/UNKNOWN 声明。 | Location 还没有 typed owner、地址坐标单位、覆盖根关系；label 不是解释器。 |
| `:209–234` ReferenceValue | 引用 SSA；可能 targets；保留 UNKNOWN selector。 | referent_identity 字符串不是动态 lifetime；targets 相同不证明同对象，不同 targets/IDs 也不是物理不 alias 证明。 |
| `:370–409` StateAccess | owned before Use、after Value、read/write mode、reference Use；唯一原状态生产者。 | field/dict key/descriptor 与 byte selector 目前无法精确区分。 |
| `program/validation.py:428–515` | 每 block 携带全部 region 状态域；按 LocationID 检查当前版本；reference/footprint 声明一致。 | 当前没有跨 LocationID 的 coherence 更新或 owner/selector 不相交证明。 |
| `:517–556,576–621` | CALL 原参数/结果；INVOKE NORMAL/RAISE 的独立状态端口；未知 INVOKE 两条边产生全部状态域。 | 有类型的调用路由不证明真实 caller/object/content identity。 |
| `execution/content.py:54–180` + `content_validation.py:404–427` | ValueOccurrence → scoped ObjectIdentity 或 DataIdentity；Reference 不能永久绑定内容版本。 | ObjectIdentity 相同不意味着内容不变；DataIdentity 相同不意味着对象、物化、alias、ready 相同。 |
| `content_validation.py:473–532,567–590` | ContentRead 接原 Use/Access；检查实际 before-state support、reference Use 对应、Mat/version；保留 state-version correspondence/stability 未证缺口。 | 这些关联尚未自动证明 root 某 selector 的内容等于指定 LogicalVersion。不能把当前 gap 删掉充当实现。 |
| `program/resources.py:174–204` ResourceUse / ResourceLocation；execution resources | 原 handle Use、requirement 与静态资源 location；动态实例/别名 handle/realization 已单独建模。 | 两个 handle 对象不同不能推出 OFD/文件内容不同；资源位置关系本身不提供 owner/key 地址、非 alias 或当前内容证明。 |
| `program/native.py:119–178` NativeBoundary / BoundaryDomain | 原 entry/exit 槽、独立状态/alias/异常等义务。 | raw provider role、TreeSpec、FactRef 相等都不是 field lookup/writeback 或 effect completeness 证明。 |
| `v2/values.py` ValueVersion / StorageRegion / Materialization | 对象/逻辑版本/物化/geometry 分离；offset/stride 单位为 dtype elements。 | storage 地址或版本字段不可充当完整外部写探测；provenance 祖先不是所有当前 writer。 |

这是**接口缺口审查**，不是宣称现 validator 已错误授予 runtime 优化权限：当前验证主要检查声明结构；后续化简必须另满足证据、合同、失效与成本。

## 3. 最小静态接口提议

下列为可实现的字段选择，不预设几十个业务节点或新的 producer/use/state 表。

### 3.1 一个原 Access 的多地址效果描述

```text
StateAddressRefinement(
  site: ExistingAccess(OperationID, access_index)
      | InvokeStateOperand(OperationID, state_use: UseID),
  effects: tuple[AddressEffect, ...],
  coverage: existing Completeness,
  source: existing source/fact reference
)
AddressEffect(
  owner: RefOwner(UseID)
       | ResourceOwner(ResourceRequirementID)
       | AmbientOwner(typed scope)
       | UnknownOwner(reason),
  selector: typed selector,
  mode: existing AccessMode            # 该地址请求 READ/WRITE/READ_WRITE
)
```

ExistingAccess 的非负 exact index 选择原 Operation.accesses；root 从原 `access.location` 派生。INVOKE 没有普通 StateAccess 时必须走 InvokeStateOperand：state_use 必须是该 op owned invoke_arguments 的 StateVersion Use，root 从其原值.location 派生；当前前态及每 NORMAL/RAISE 后态只沿原 completion 端口派生。不重复存 before/after/producer，未观察到 completion 不补 after，更不能默认 NORMAL。

一个原 site 最多一份聚合描述，但其中必须允许多个地址 effect。现 core 一 op 每 LocationID 只有一个 StateAccess：Torch op 同时读 x、读 y、写 out 时，同一 root 的三个地址项必须共用原 READ_WRITE before/after，不能遗漏两个输入或额外造三个 state after。

每项 mode 是该地址的请求；ExistingAccess 下必须被原 access.mode 包含，不能覆盖原 root summary；InvokeStateOperand 仍是边界输入细化，不能从 mode 推造 StateAccess 或证明 native 写已发生。tuple 不声明内部访问顺序。owner/key/index 每项分别指向原 Use；INVOKE 应为真实 invoke_arguments 的原 Use，不能用 successor-only forwarding Use 冒充 native 输入。可以复用同一个真实 Use 描述它实际参与的多个地址，不另制造 consumer；`f(x,x)` 原本两个 Use 也不能合并。地址完整性是单独的声明，PARTIAL/UNKNOWN 或缺整份描述时保留 coarse 未解析余量；不从 tuple 非空、空 tuple 或 Operation.effects_complete 自动推导细地址全集完整，更不是 native proof。

新描述不存在的 access、跨 op 的 Use、错误 role、缺 resource Use/requirement 归属是结构 issue。多地址效果不能产生新独立版本；细 selector 请求是否真落在此目标，需要后续明确协议/证据而非本门执行 Python key/descriptor。

- RefOwner 必须是此 op 的原 Reference Use；各项均受其 targets/root 声明约束，不能以同 ValueID 代替端口身份。ExistingAccess 的 legacy `StateAccess.reference` 如存在，继续保留原约束，不得改写；多 owner 情况不要求**所有**项都等于它。若声称地址列表完整，必须保留这个已知 anchor 的对应项；PARTIAL 可只提供其他项，但遗漏原 anchor 不能当作它没有参与访问的证明。
- ResourceOwner 引用此 op 已有 ResourceUse / requirement；动态 owner 由同一次 occurrence/activation 的 RequirementBinding / ResourceAccessBinding 派生，不复制 target。已声明 handle 时不能绕开其原端口。
- AmbientOwner 只允许明确的 RUN/PROCESS/HOST_THREAD/ACTIVATION 等 scope 变体；从 occurrence 派生作用域。未知 thread 继续 UNKNOWN，不造 Python 对象。module/global namespace 通常是原引用 owner，不按字符串模块名赋身份。
- owner 不是“一个全局 ReferenceValueID 代表永久对象”。同一静态 op 的每次 occurrence 重新沿原 UseOccurrence 解析；跨调用沿既有 actual→formal/CallActivation 路由回查，不能用名字接线。

### 3.2 Selector 的语义边界

最少需要 whole-owner、attribute lookup、item lookup、slice、storage/protocol、unknown 几类**有类型的描述**；这不是声明这些操作互斥或纯。

- 动态 key/index/name/slice component 必须引用原 op 的独立 UseID，求值依赖保留。省略的 slice component 与一个未知值不同；显式 None 也应保留原语义位置。
- 源码 `o.x` 的静态名字可保留 exact source field，或前端显式投成现有 literal+Use；禁止分析器临时执行 `getattr` 获取这个“字段”。动态 getattr 的 name 是原 Use。
- `AttributeLookup('x')` 不应命名成已证 physical field；`ItemLookup(k)` 不应命名成已证 dict entry。协议解析后才知道是 exact builtin 直达存储、descriptor、代理、mapping subclass 或任意 native 调用。
- storage geometry 继续引用原 scoped RegionRef/Mat；别复制 shape/stride/offset 或把通用 Footprint.interval 自动解释成 bytes。key/index selector 也不能被解释为 byte offset。
- ProtocolSelector 的 FactRef 只是来源。无 whitelist 解释器、原端口映射或 coverage 时，结果仍 UNKNOWN，不从 FactRef 相等推出地址相同。
- UnknownOwner/UnknownSelector 不是 NONE、empty、disjoint 或 WHOLE 的同义词。明确 empty 范围可以无内容交叠，但不消除异常、回调、allocation、I/O 或 ordering 效果。

### 3.3 必须同时冻结的 root 规则

1. 保持旧 Footprint 的 root 坐标解释；新 owner/key 地址不悄悄重定义旧字段含义。
2. `full_overwrite=True` 只能表示整个 root 被覆盖。现 validator `:480–485` 将其 before role 改为 STATE_ORDER；“写完整字段/对象/选择切片”**不能**抹掉 root 其他内容依赖。细地址不得单凭 WholeOwnerSelector 授予 full_overwrite。
3. unknown effect/callback 的 op 仍需原粗状态效果；描述一个已知字段不能将该 op 的其他未知效果消失。NORMAL 与 RAISE 都保留实际 post-state，异常前写入不回退。
4. 普通 CALL 没有重复 access summary，应由 callee 原访问描述，经现 call 端口组合；INVOKE 的 opaque boundary 通过原 state operand 表达请求，但不借 callee 名字制造细效果证明。多 op 子区合成仍返回 root 原 SSA，不新增 field SSA。可选 stage 标签也不代表未知/未发生 completion 上已发生 write。
5. `effects_complete`、Stability.INTERNAL、owner/selector 已知各是不同声明；任意一项都不是 runtime alias/coherence 证明。未知外部写窗口不得被 INTERNAL 标签抹去。

## 4. 动态 denotation 与证据：尽量复用，不加地址 epoch 状态机

派生只读地址视图可以是：

```text
原 AccessRef(op occurrence,index) 或 InvokeBoundaryStateEffect
 → 原 StateAccess / invoke state operand / current before UseOccurrence
 → 原 owner UseOccurrence / selector operand UseOccurrences
 → 既有 ValueDenotation(ObjectRef / Data VersionRef) 或显式 gap
 → 既有 ContentRead / original placement / scoped RegionRef
```

- root 的动态版本是现 ValueOccurrence（包含 loop visit/incarnation），不增加按对象维护的另一套 version counter。静态 ValueID/LocationID 反复执行不合并这些 occurrence。
- 两个引用有同一 scoped ObjectRef：可声明同对象，不能合并两个 Use 或其读取时刻。内容改变后 ObjectRef 可不变，root after 和读取所得版本/物化必须按本次状态重新关联。
- 对象、allocation、Mat、逻辑值各有不同身份范围。同一 allocation 上不同 view/不同 dtype 的 byte overlap 用已有 geometry；不同 allocation 也可能通过外部映射共享数据，不得默认全局 disjoint。
- 现 ContentRead 已有 effect/support/basis，可以承担“此次 access 在当前 root 下读该内容/物化”的条件关联；不需要另造第二张读取事实图。其 `content_state_version_unverified` gap 只能由明确 protocol/source correspondence 实现关闭，不能因地址字段齐全就删除。
- **现细地址连接边界**：`content_validation.py:503–510` 对 UseRef 读取要求原 effect 的单个 `StateAccess.reference` 精确等于 subject Use。因此一个 root access 的多 owner 细分请求，不等于已支持 x/y/out 每一项独立内容证据。当前门保留该 guard，不冒认额外项已闭合。后续若需要逐项 ContentRead，可引用原 refinement site + effect index 作为对应锚，仍复用同原 root/effect/current state；这是新增的精确关联需求，不是字段 SSA 或新 producer。本门不靠删 guard 通过。
- 原始 source inventories、unknown/opaque effects、escape、外部可变窗口、读写间 order/lifetime 义务全部保留。没有观测到写不等于没有写；缺 alias 覆盖就是缺口。来源 artifact 精确哈希可查不等于采集完整。
- 本门可以校验同 root、原 Use/Access、scope、当前状态与来源连接；不能仅由类型实施缓存、hoist、DSE 或内容失效豁免。没有必要存 Tensor 每迭代数值；前几个值/shape/hash 也不能证明未变或可替换。

## 5. Python / PyTorch 主源核对

以下不是新运行见证。

1. Python mapping 协议按 hash/equality 寻址，不按 `(type,value)`、repr 或 ObjectID 分 entry；exact builtin dict 的 `1/True/1.0` 可命中同一槽。自定义 hash/eq 可有回调、异常和状态依赖，不能在分析器里调用它们来构建 selector key。[Python 3.14 dict](https://docs.python.org/3.14/library/stdtypes.html#mapping-types-dict)。
2. Attribute lookup 可能经过 `__getattribute__`、descriptor 与 getattr；property 不是普通实例 dict 槽，setattr 也可执行自定义代码。静态名字相异不排除跨字段/全局副作用。[Python 3.14 data model](https://docs.python.org/3.14/reference/datamodel.html#customizing-attribute-access)。官网此次返回 3.14.8 文档，不宣称这是本机 3.14.7 的逐字源码。
3. 本机只读 `torch/version.py`：`2.13.0+cu132`、CUDA `13.2`、git `cf30153c4c131c8164ee7798e5022d810682e2cb`。没有 import torch 或更改环境。
4. 本机 `_torch_docs.py:4414–4418` 明确 from_numpy 共享内存；`autograd/graph.py:245–259` 说明 PyTorch 未知的外写需显式更新版本，inference tensor 无该 counter。因此 `_version` 不是全写入监测器。NumPy alias 写、外部 native pointer 写必须进入同 storage/root 的失效义务，缺采就不能证稳定。[对应 PyTorch 源](https://github.com/pytorch/pytorch/blob/cf30153c4c131c8164ee7798e5022d810682e2cb/torch/autograd/graph.py)。

具体避免两种伪规则：同 hash 不等于同 key；不同 ObjectRef 不等于无 shared storage/底层资源。exact builtin key 的规范化只能在受限、可验证、不运行用户代码的协议内做；一般 Python equality 不可随意 DSU 化为永久等价类。

## 6. 建议验收分母：20 组必要正反例（全部待实施）

这里是**20 组拟定验收**，不是 20 tests PASS；每组的子变体必须报告实际数量。先类型/接线，再受限协议，不以自动 frontend 或 runtime 证明冒充通过。

| ID | 必需构造 | 应有结果 |
| --- | --- | --- |
| A01 | `a,b` 两原 Use 指同 scoped ObjectRef；经 a 写、经 b 读 | 保留两端口；读消费 root after；不复用旧内容。 |
| A02 | 同对象原位覆写；ObjectID 不变、两次内容不同 | 对象身份不改为内容身份；旧 ContentRead/Mat 不自动为新 state 有效。 |
| A03 | 相同 static owner ValueID 在两 activation/loop visit 代表不同对象 | 各自 actual UseOccurrence 解析；不按静态 ID 合并。 |
| A04 | 两个不同容器 owner 共享子对象；shallow copy | owner 不同仍可能 alias；复制容器不等于复制全部内容。 |
| A05 | coarse unknown root write 后细 field read | 旧 root before 被 stale guard 拒绝；正确 after 接线合法。 |
| A06 | 细 field write 后 whole-root read | whole-root 读必须取 after，不能保留旧 world。 |
| A07 | 相互 overlap 却各自独立 LocationID 的 coarse/fine 声明 | 新接口不授 coherent；同根重写或完整显式同步更新才可组合。 |
| A08 | WholeOwnerSelector 写一个字段，同时 root 另有字段 | 不允许冒 root full_overwrite/STATE_ORDER 擦除其他内容依赖。 |
| A09 | exact dict 的 key `1/True/1.0` | 不能以不同类型字面量宣布三个独立槽；原 Use/值类型仍保留。 |
| A10 | hash 碰撞但不等的 keys；自定义 hash/eq 有写、raise | 不按 hash 合并；无受限协议时保留回调/异常及 current post-state，不执行用户 eq。 |
| A11 | `property x` 读时递增 counter；自定义 getattribute | AttributeLookup 不能成为 pure field read；counter/world 写不丢。 |
| A12 | descriptor/setattr 写 x 却改变 y、外部 owner 或 class；后续 monkeypatch | 不以名字不同判 disjoint；class/protocol 状态与异常保留。 |
| A13 | Torch from_numpy + NumPy 外写，Torch counter 不足 | shared allocation 内容稳定性保持缺口/失效；不能以 counter 或采样缓存。 |
| A14 | 不同 view 对象、zero-stride、部分 strided overlap/holes | 使用 scoped allocation/byte geometry；不造 expand allocation、不用 bbox 填洞。 |
| A15 | 两 Python handles/dup 共享 OFD offset；独立 open 共享 file content | owner 对象与资源身份分离；offset/content 域正确绑定，不以 handle ID 判独立。 |
| A16 | 明确 empty selector、unknown selector、whole owner/root 四种 | 四者不可混同；empty 不消除 op 其他效果。 |
| A17 | 同 root op 读 x/y 写 out 三地址；再变异 foreign owner/key Use、缺 key、错误 resource requirement owner | 合法多地址共用一个原 before/after，逐项保留原 Use 与 mode；错归属明确 issue，PARTIAL 余量不消失。 |
| A18 | opaque INVOKE 无 StateAccess，state operand 细化；key/hash/descriptor 回调后 RAISE、已部分写 | 正确 state Use site 可表达；错 operand/edge-only owner/key 拒绝；两 actual completion post-state 接原接口，无 completion 不补写/after。 |
| A19 | selector/owner 已知但 source alias inventory 不完整或预算截断 | UNKNOWN/gap/未检查游标保留；不能授权 nonalias/完整覆盖；未关联 effects 仍在分母。 |
| A20 | Legacy graph 无地址；仅新 typed 地址；有来源声明但无 runtime witness | 旧 wire 原语义不升级；新描述只声明结构/协议，runtime/native/transform 权限保持未证。 |

## 7. 实施顺序与不新增的东西

1. 冻结同 root / original-access **多地址 effects tuple** 与 full_overwrite 规则；所有 owner/key/index 接线可由已有 Use/Access 校验。
2. 构造层 strict types + 图级结构正反例；地址协议解释与 unknown 边界分别验收。legacy 仅按既有语义读取，wire 若增加字段应另显式版本化。
3. 先由 canonical constructed fixtures 证明 coarse↔fine/异常/调用组合接得上；不把 source 自动 lowering、捕获 identity/lifetime、Python 任意回调解析计入本门完成。
4. 动态只读连接复用现 ContentRead/ValueDenotation/ResourceAccessBinding 与 inventory，明确未证 correspondence；后续优化另立 obligation。

不新增 per-field SSA、地址 epoch 状态机、第二张 producer 图、大 tensor 取值快照或 LeWM 规则。若 root 与 field 尚独立前进，本门就不能宣称 coherence 建模完成。

## 8. 阅读指纹

```text
3a72c7692afdb19f74f19df5990527140e360748954c64dde3e335551580b2b1 scar/ir/program/model.py
04ed471b6164b14e738ed0c22aee16f256f2a925038321a478834ef68aff7264 scar/ir/program/validation.py
167f0b2e1267278362341e6622e5cb164292e93484da94c8403b382e1e6e434f scar/ir/program/resources.py
f2709a6d9e9898bc5ecb87ae2396510750550fde1bb071f8ab9808569f352c39 scar/ir/program/resource_validation.py
17543d01b8351d74eefc665d48c74383bca27d820507fff98646dc3cef2a22b0 scar/ir/program/native.py
7fb36d01c70dc36889cf6dea65aa23763c0dd5139afc1bccdee65324e5e2743b scar/ir/program/native_validation.py
1eee1822056e59a0be9f4f3a1524f97948df91497ad57072c7c0ca53c670cf9e scar/ir/execution/content.py
e54ec95c69d80b5e00d4b59e4f98aca1bf3c9a9029bde28f0b7bae0f9043071f scar/ir/execution/content_validation.py
b19e45c8af710b93d7197ca91e7cbcdfa7a9ee239a7faf73903d2ff85003ce09 scar/ir/execution/coordinates.py
2b6189a1ad658072176a00bc4c72a4c5af4c66e96edc844bad904471c8eb0501 scar/ir/execution/flow.py
2c4ab8a69d46ef312f454c487329150cd7f3f4a12819e51bf8a8ae218210f259 scar/ir/v2/values.py
d11e038a6a4c7de6dee5c8050182a97ddb4a6a6a399c466836ca64d6d9cb0a23 scar/ir/v2/ids.py
ea4bb6cd1d4976ad7e6d1b7ccd214c5cdeafa0f657623e2363fd110bada9e509 docs/WHOLE_PROGRAM_MODEL.md
5033fd3221d112dcebcbf087788440d7545effc88330dff589ed3ed4cdd482e4 docs/model/RESOURCE_PROTOCOLS.md
74a606fca89ecb94ad9a04f77d8ad41706bcdacb10210352ccad185272993729 docs/M1_RESOURCE_EXECUTION_CONTRACT.md
0b7eed250389a0312e365f539bd3f745e9cc1a4c1aac2d341a8d18a9302ee8f6 installed torch/autograd/graph.py
38bd167709f8998348da6aaa926b3af3cf2d6e8eb525ac3026d58a256ade1b90 installed torch/_torch_docs.py
```

同事并发设计不包含于此源码基线；本文只固定本轮读取和 Proposed 选择。没有执行 Python、自动建图、runtime alias probe 或任何 test。
