当前 core 把必要语义依赖与其 Python/SCAR 编码操作混在了一张图中。应保留依赖、折叠管理操作；不能因节点叫 Frame/SSA 就全部删除，也不能把它们逐项算作用户可化简的程序操作。本审计未改 main、旧图或资格。

实查 Root 已普通读回的 239-op SP5：`omegaconf/dictconfig.py:341–359`，原 artifact 双 SHA 见 `OBSERVATION.json`。图有 540 values、19 BindingDefinition、9 BindingRead、1 environment、1 cleanup、2 exception match、16 exception packet、18 pending completion。**单独 FrameModel 实际为 null**，Frame 行为来自 structured protocol。239 ops 中，113 个是 packet/pending/dispatch/转发/异常出口编码，54 个是 frame 管理，另有 19 个纯 local-binding 定义；这些数量不等于可删除操作数或运行成本。完整来源上下文占 21,668,986 / 23,597,704 decoded bytes（91.83%），body graph 本身仅 877,089 B。最先应共享来源上下文，而非增加底层节点。

| 决策 | 具体实体及当前 consumer | 必须保留的含义 / 可折叠边界 |
|---|---|---|
| 保留操作与依赖 | `model.py:Operation/Use/ReferenceValue/StateVersionValue/StateAccess`；`queries.py:ProgramSnapshot.state_address`、`source_body_access.py:bundle` | 源操作/API、原输入输出、顺序 Uses、别名、读写地址与前后状态；未知 effect 不等于 pure。同值/同 shape 不能合并不同 occurrence。 |
| SSA 作为边/端口 | `model.py:LocalBindingValue/BlockArgument`、`bindings.py:BindingDefinition/BindingRead`；`binding_validation.py:validate_bindings` | BOUND/UNBOUND、reaching definition、条件合流与可能的 UnboundLocalError 不能丢；纯绑定定义与转发 jump 可从主操作视图折叠，保准确 slot/value/control 边。 |
| 保语义，折叠控制编码 | `control.py:ExceptionPacketDefinition/PendingCompletionDefinition`、`cleanup.py:CleanupEnter/Resume/Replace`；`cleanup_validation.py:analyze_cleanup`、`ProgramSnapshot.cleanup_route_steps/exception_match` | 保 exception+traceback、return/break/continue payload、handler 顺序、finally 覆盖/继续及 handled-context 恢复；pack/unpack/token/dispatch 的内部选择编码可折成有类型的控制/清理边。不能猜 traceback=None。 |
| 条件保留生命周期影响 | `frames.py:FrameModel` 与 `structured.py:PythonProtocolKind.FRAME_*`；`frame_validation.py`、`source_function_try_validation.py`、`source_call_validation.py:_local_pending` | 当前普通 reader 用这些记录核持有/转移/异常清理；但 INCREF/临时栈/每个 HOLD 不是独立优化目标。保可能可观察的最后释放、finalizer/weakref 回调、资源逃逸与异常先后；不对每次逻辑持有都强加全 world 运行成本。未证明无回调时不能直接删状态边。 |
| 编译/验证证据外置共享 | `structured.py:StructuredBodyModel/PythonProtocol`、`source_language.py:CodeConstantSource/CompilerLocalMapping`，及原 `semantic/semantics/control`；`require_valid_structured_body`、`SourceCodeEvidence`、`SourceProgram.read_structure` | 源/编译一致性、closure 布局和来源身份必须可核；code index/精确 bytecode staging 主要是 adapter 证据，不是主视图计算。按原 source/context 三 hash + namespace 引用共享，保不可变 owner/输入变更 guard；不能缓存可变 IR 的“验证成功”。 |
| 不扩入核心 | CPython operand-stack 布局、opcode dispatch、refcount 算法、解释器 frame 实现；本样本无 resource/native/provider 子图 | 它们不因存在于解释器中就成为可化简对象。仅在其接口效果影响源程序正确性/资源成本时保摘要与按需证据。当前 entry router（`source_entry_routing.py:37–58`）消费普通 body 的原 formal ports，而非每个 HOLD/opcode 阶段。 |

**FunctionDef 收敛**：外层保 defaults 的真实求值操作，以及一个 typed function-creation 接口（原 code 引用、globals、defaults 值、按序捕获 cell identity → function reference、正常/异常 post-world）和原 name/cell 写入依赖。注解 thunk 只引用原 code/captures，不执行、内嵌子 body 或复制上下文。MAKE_FUNCTION/SET_ATTRIBUTE 的逐阶段序列保为该接口的静态验证材料，不强制成为主视图节点。复杂 decorator/type-parameter/未知 annotation 形式保精确 frontier。当前未启用的逐 staging 草稿将保留，再依此边界收敛。

成本：只检查上述一个原 SP5，无 typed reader/lower/compile/target；两次检查脚本字段假设失败后重读，累计 stored 7,772,271 B / decoded 70,793,112 B，均已计入观察收据。不将 JSON 检查当新源码或 runtime 证明。旧 schema/原产物不改；折叠/共享是后续受控表示改口，不能倒授已有模型优化资格。
