# 委托 iterator callback 的异常上下文：CPython 3.14.7 小见证

## 目的与范围

这个独立标准库探针检验一个具体分支：父 generator 在自己的 except A handler 中暂停于 yield-from；外部 caller 在 except B 中调用父 generator 的 throw 或 close；委托 iterator 的 Python throw/close callback 观察到哪个 sys.exception()。

结果确认了担心的路径：普通恢复回调和 throw/close 快路径的上下文不同。代码仅记录异常类型与 identity 布尔值，不保存 frame 或 locals。环境 CPython 3.14.7 / conda lewm。没有导入 SCAR、PyTorch 或运行目标程序。

## 观察到的结果

脚本有 4 组观察，未捕获错误 0：

1. **普通 next/send 恢复**：parent yield-from 暂停在自身 ParentError A handler 后，caller 在 CallerError B 的 except 内调用 next(parent)，委托的 __next__ 观察 ParentError A；caller 随后在另一个 CallerError B handler 内 send(parent)，委托的 send 也观察 ParentError A。每次调用返回后，caller 重新观察到自己的 B。
2. **throw 转发且委托器 yield**：在 CallerError B handler 内调用 parent.throw(InjectedError X)，委托的 throw callback 观察到的是 caller 的 B，而不是父帧保存的 A。委托器返回新 yield，parent.throw 将它直接作为结果返回；外层 B 仍恢复。
3. **throw 转发后委托器抛回 injected exception**：委托的 throw callback 同样看到 B。callback 抛出同一个 X 后，异常进入父 generator；父体局部 handler 看到 X。局部 handler 结束后，父体恢复到其保存的 ParentError A 状态，并继续 yield；外层 caller 的 B 也恢复。
4. **close 转发**：在 caller 的 B handler 内调用 parent.close()，委托的 close callback 观察到 B，而非父帧保存的 A。close 随后完成，inspect.getgeneratorstate(parent) 为 GEN_CLOSED，外层 B 恢复。

因此，观察结果支持这个更窄的解释：常规 yield-from 迭代发生在父帧恢复过程中，回调看到父帧 A；CPython 的 generator.throw()/close() 对 yield-from delegate 的专门分派先调用 delegate.throw/close，此 Python callback 看到外部调用点当前的 B。不能把三种 callback 都标为“在父 generator 当前 handled-context 下执行”。

这是对 CPython 3.14.7 自定义 Python iterator 的实际观察，不证明其他解释器/版本、C 实现 delegate、其他 yield-from iterator protocol 组合都同样实现。它也没有表明父 generator 的 handler 被永久改成 B；throw 后父体继续时仍恢复 A。

## 对模型的具体要求

- 一次 resume occurrence 必须注明执行阶段：恢复父帧中的 body operation，或从 host 驱动 API 快速调用 delegate protocol。请求 kind 单独不够决定 callback context。
- DelegateActivation 的 throw/close callback 是真实独立的调用边，需携带其实际调用方 handled-context。若 runtime record 没有这项关联，只能标上下文 unknown/conditional，不能从父静态 frame 的保存状态复制 A。
- 当 delegate.throw 返回 yield 值时，这一结果是 parent.throw 请求的 host result；父 body 尚未重新运行。若 throw callback 抛异常，该异常才进入父帧，并按父体 handler/cleanup 状态继续。
- close callback 返回后，才可能继续把 close/GeneratorExit 交给父帧；不能用 callback 发生来提前标记父 body Closed。该探针末态 GEN_CLOSED 仅说明本样例的整个 close 成功。
- 上述是补充 C2 异常上下文模型的 adapter 分支；不改变“同一个 body + temporal successors + typed extra availability roots”的静态 CFG 方案，也不证明 source lowering/runtime tracing 已实现。

## 可复现文件

运行：

    source /home/zyf/miniconda3/etc/profile.d/conda.sh
    conda activate lewm
    PYTHONDONTWRITEBYTECODE=1 python artifacts/experiments/b1_call_operands/model_resume_interfaces/review/language-delegate-context-probe.py

probe JSON 记录：CPython 3.14.7，4 个组，script SHA-256 为 90af01e0faae655a8219926d0d48cd55292ea2e3145733fe26b6a64648b4eb29。原始 JSON SHA 在归档时随文件单独计算。
