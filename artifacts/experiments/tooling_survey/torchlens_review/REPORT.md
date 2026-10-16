# TorchLens 补充审查：已有细粒度动态图应优先评估复用

日期：2026-10-16。固定官方 revision `550b96a61972cf7db23044125e5ee63489d217cd`，pyproject 标称 2.36.1。
**范围：官方文档/包声明审查；没有安装、import、运行 forward、GPU 或 LeWM。**
成功读取的来源大小与 SHA256、首次错误相对路径的 404 均见 source_receipt.json。
原始第三方文档只在本次专属目录临时读取，核对后删除，不将它们全部 vendor 进 SCAR。

## 1. 不能忽略的已有能力

[README](https://github.com/johnmarktaylor91/torchlens/blob/550b96a61972cf7db23044125e5ee63489d217cd/README.md) 描述 eager Torch 操作、Tensor 依赖、模块嵌套、循环/动态路径
与反向关系的记录/展示。这比只看 module 树细，适合成为现有动态 observer 的候选
替代/补充，不应重写一个相同功能的 Tensor tracer。该描述是上游能力声明，不是
本机 3.14.7 / Torch 2.13 兼容性验收，也不证明整个 Python 程序依赖恢复。

## 2. 接入前必须保留的捕获条件

[限制](https://github.com/johnmarktaylor91/torchlens/blob/550b96a61972cf7db23044125e5ee63489d217cd/docs/reference/limitations.md) 表明 wrapper 逃逸的某些恢复可再次执行
forward；模型含状态、外部交互或 RNG 时，第二次执行必须有单独合同。编译模型可
回到 eager，因此所得图不能当作原 compiled kernel 执行证据。它还明确记录未覆盖
的 closure/global Tensor、native/dispatch、mutation 等情况；不得把缺失当 NONE。

[性能与内存控制](https://github.com/johnmarktaylor91/torchlens/blob/550b96a61972cf7db23044125e5ee63489d217cd/docs/performance.md) 提供选择性 payload 保存、窗口及开销
控制；减少 payload 仍不等于没有引用/副本/observer 成本。采集状态、退出释放及
跨调用对象存活必须单独核查。SCAR 不因此允许默认保存每轮全部 activation，
更不能为省内存默默将可求梯度的程序改成 inference 模式。

## 3. 无值结构模式不是实际值依赖的证明

[结构模式合同](https://github.com/johnmarktaylor91/torchlens/blob/550b96a61972cf7db23044125e5ee63489d217cd/docs/reference/structure_only_capabilities.md) 与限制页都区分
结构事实和待实值核对的 hypothesis，存在值依赖分支时还有限制。这个固定 checkout
的结构合同仍有 D8 queued/default 描述，而限制页另有 meta admission granted 描述；
两份文档的阶段文字不完全一致。不能仅凭 README 选项推断本机实际可用范围。

## 4. SCAR 的具体复用决定

- 在后续 adapter 阶段，与 ETO+Kineto/FX-Export 同一组通用正反例比较，按所需事实
  及采集成本选择 provider，而非默认叠加全部 observer。
- 导入原始 artifact、版本/模式、未验证边界和捕获效果；Tensor use 只能映射到
  canonical occurrence，不将上游 layer barcode 当作 logical version。
- 评估前先做隔离 CPU 兼容试验：重复实参、view/in-place、外部 NumPy 写、闭包
  Tensor、buffer/RNG/异常、未走分支和编译模式；不需要新 optimization backend。
- 本轮不实施新 adapter；第一阶段仍先完成规范模型的组合接口。
