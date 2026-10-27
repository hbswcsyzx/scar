# LeWM 自动函数环境接线：真实建模记录

2026-10-22。产品提交 `545fa4c`。**第一阶段仍 OPEN。**

## Observed

`bash run.sh`：conda lewm / Python 3.14.7，原始 LeWM 入口、同一 raw calls、
151 个文件和原预算（256 body attempts / 10000 construction operations）。
这是重建真实执行对应的源码模型，**未重新执行推理**，不是 workload 性能测量。
exit 0，wall **639.67s**，peak RSS **394456 KiB**。

| 项目 | 原 structured inventory7 | 新 environment inventory8 |
| --- | ---: | ---: |
| 文件 / 定义 / 调用 / 源 atom | 151 / 2217 / 10235 / 122323 | 相同 |
| LOWERED_WITH_GAPS | 51 | 54 |
| UNSUPPORTED | 205 | 202 |
| NOT_ATTEMPTED | 1961 | 1961 |
| code/source CORE_LINKED | 33 / 425 | 34 / 425 |
| core operations / values | 1486 / 2283 | 1660 / 2886 |
| construction operations | 5592 | 6765 |
| CONNECTED source atoms | 697 | 779 |

自动产出 54 个既有 EnvironmentInterface、3 个 captured-cell 入口、60 条
PARTIAL state address refinements。每文件 prepare 一次，unavailable contexts=0、
unknown construction costs=0。不存在按 workload 名称选择的分析规则。

## 原 45 个 closure 拒绝去了哪里

`comparison.json.old_45_environment_failures` 保留每个原定义、新 status、下一
reason，以及环境图是否最终保留下来。**只有 3 个最终成功；42 个仍回滚，
不能说它们已有完整环境图。**

- 25 个继续遇 heap/global/destructuring 写；3 个 expanded Call。
- 2 个 Raise、2 个局部 slot、2 个 BoolOp、2 个 AnnAssign。
- With、ImportFrom、JoinedStr、GeneratorExp、AugAssign、IfExp 各 1。

成功的三个是外部源码的 `_make_log_filter._filter`、
`GPURandomResizedCrop.__init__`、`UniformTemporalSubsample.forward`；这是自动
队列的结果，不是内部的函数匹配规则，也不是优化发现或加速结果。

新总首个阻塞：heap 写66、expanded Call18、BoolOp15、Raise11、IfExp9、
Dict9 等；全部原始细节见 comparison。首个阻塞不能代表 body 后面没有别的缺口。

## Implemented / Verified / 尚未验证

已实现源码→compiler layout→环境入口→cell/namespace owner/key/world 接线，
正常/异常各自携后态；同 code 不能合并不同环境。新 public profile 输出
SourceProgram4 / inventory8，旧 structured/frame 路径不改义。

按用户要求缩小测试：shared 接线时的 26 项旧回归已通过；只执行 1 个新闭包
入口检查（0.85s）。第一次该检查因顶层 raise 后的函数被 Python3.14 compiler
删除而正确拒绝；将测试 marker 改成“若执行会失败、但编译保留声明”的未知调用
后通过，未放宽生产 matcher。其它已写新测试本轮未运行。

独立标准库 `compare_inventory.py`（无 scar import）全量核对旧新源码 snapshot、
三图 context、原始 calls、预算和 body 分母，并重计状态、覆盖和环境声明归属，
结果 valid=true。它不是依赖真值或运行时环境 proof。
**本轮未再跑耗时的完整 public check-inventory 重建**；不能称 inventory8 已通过
公开全量重放。旧 inventory7 的公开重放结果保留在前一份报告中。

实际 function/globals/cell/defaults 身份、精确 effects、逻辑值来源、OS/CUDA
资源与 ready/输出生命周期仍未闭合。旧 raw calls 无环境 actual，无法事后补造。
whole_program、fine_effects、runtime_environments、transformation 全为 false。

## 下一项

针对这次真实的66个首个写入阻塞，补 Attribute/Subscript receiver/key 的准确
来源和状态写；旧 source overlay 缺 receiver/key computational records，但原
SG 有对应，应在新 adapter 接线，不能改旧三图摘要。并行补 BoolOp/IfExp 的
条件与取值路径，防止多做一次 truth。随后按新实际终止点继续第一阶段。
没有 detector/backend、代码化简或性能 A/B。

`base.git.txt` 是运行启动时父提交；`implementation.patch` 保存当时 tracked
改动，新增产品文件由 `implementation.git.txt` 指向的545fa4c完整保存。运行中
未改其导入的产品代码。独立开发且尚未接线的 heap/conditional 文件不属于本产物。
