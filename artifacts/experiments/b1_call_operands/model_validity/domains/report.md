# V domains / order / stability：owned 实施记录

本次只修改三个新模块、两个新 unit 文件及一个新 fixture 文件；未修改其他 owner 的源码、旧测试或冻结合同。基线由 root 指定 `f2b4672`，没有执行 git、full、GPU、LeWM 工作负载或安装。

## 已交付

- `validity_validation.validity_errors(ctx)`：初始化四类 resolved dictionaries；无新表时立即返回。Host/External EstablishedProduction 不造 work，复用 root 的 `resolve_actual_range`；结果 occurrence 独立 FK/run/实际 host result/completion 检查。实际 BEFORE 不能代替 AFTER/选定 EDGE。
- `resolved_establishments[id]`：`row,write`（resolved write）,`original_write,actual,requested,rawprofile,raw,protocol_result,actual_ref,established,status,conditions,gaps`。
- `resolved_lifetime_events[id]`：`row,target,at,stage,effect,retired,status,conditions,gaps`。LIVE/RETIRED 保留声明/未解析协议条件；不从 handle end、BorrowRelease 或 enum 得到 native free。
- `resolved_order_associations[id]`：`row,before,after,basis,strength,status,gaps`。source HAPPENS_BEFORE 不从粗 WorkEvidenceBinding 升级 whole-ticket Start/End；该范围明确 ASSUMPTION。准确 host AFTER/实际 EDGE→BEFORE 配对与已有实际 host/queue 关系可条件解释。strict self/reverse/联合环拒绝。
- `resolved_supports[id]`：`row,read,write,production,actual,domain,visibility,order,basis,status,conditions,gaps`。`resolve_support(...,budget=shared)` 在 query 重新按共享预算查路径；不免费复用验证时的 cached path。
- `validity_stability` 导出 `production_interval/read_interval/read_domain/stability`，ResourceConsumer 保守使用 WorkStart..WorkEnd。扫描独立来源、所有原 WRITE/RW/未知 INVOKE/不完整效果、target lifetime 与准确 consumer handle end。只排除准确 source stage/effect，不按 owner/ticket 排除。
- source overlap 仅按对应 write 的实际 produced selector 判 definite；request-only 保留 potential。producer 内部写可能被后续阶段修复，保留 potential；只在保守 production_end 之后至 read_end 的已知 actual overlap 判声明级冲突。Geometry 复用 G describe，包括整数位宽、rank、layout/dtype 与共享预算 guards。
- `source_result_barrier` 复用 root closed `_profile`，从准确 RawRecordRef 或同 bundle source instance 的 raw line/hash（含 return boundary）回原结果；零字节也是已见结果。删除 Outcome/Produced 不允许把已有结果变成 whole future request。未解析的 result 只阻止 fallback/列 gap，不造 outcome/selector。

## 明确范围

Host 同线程原效果顺序、Queued exact FIFO/event/wait→consumer Start 有机械 conditional 支持。Endpoint 的 target/Q/协议引用可以校验，但目前没有解析当前 basis 真正完成具体 endpoint facet/selector/read/flush/persist 的解释器；因此 Endpoint 仍 MISSING + `validity_endpoint_interpreter_unsupported`。相同 FactRef 不授成功。

whole-work/native 对齐、LIVE/RETIRED 的物理适用、完整 writer/alias 捕获仍未证明。Source/runtime visibility/transform 不因本层变真。真实 unsafe 声明由 query 输出冲突，不是 metadata FK 错误。没有 ready/free 权限或 LeWM 加速结论。

## 定向记录（均 conda activate lewm）

每次实际命令均为：

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
python -m pytest -q tests/unit/test_execution_validity_domains.py tests/unit/test_execution_validity_stability.py
```

stdout/stderr 合并重定向到各 `attemptNNN/output.log`。各次是递增且重叠的集合，不相加为测试分母；最终 owned 分母 **29**。

| 记录 | 实际结果 | 解释 |
| --- | --- | --- |
| attempt001 | 6 PASS / 0.72s | 第一可运行 canonical host 路径；该次未预先记录源码 hash，不补造历史快照。 |
| attempt002 | 23 PASS / 1.23s | 历史结果；随后 root 源审指出 endpoint 仅同 FactRef 的旧正断言过宽，代码与测试同时收紧。不是 endpoint 原生解释验收。 |
| attempt003 | 24 PASS / 1.23s | endpoint unsupported、独立 result/run/owner guards、queue/interval/lifetime。 |
| attempt004 | 27 PASS / 1.39s | requested16 与 actual0/4/16 对 tail 的冲突对照。 |
| attempt005 | **29 PASS / 1.45s** | 最终 source-result 删除绕过及未知线程 gap；该次运行前记录六文件 SHA。 |

没有 owned pytest 失败被覆盖；root/core 的先前 scaffold/旧 enum 导入失败属于 root 已保留的日志，不计这里的成功。最初误用的 enum 名已在首 owned 测试前统一为实际 `LifetimeEventKind`。

最终六文件 SHA（与 attempt005/source.sha256 一致）：

```text
b347ece5df59c8a6aeeb0e7421a533f1decb1c21eacd6cbaf755c3254c6a161e  scar/ir/execution/validity_validation.py
8e0c0afcf8ada6cfddbc217c6de733868406921ed85f709f7979f70951b55ad4  scar/ir/execution/validity_order.py
c394f306fe4ff318ee80badf112881f5c2b8c310b881b74253eeca66afe9aadd  scar/ir/execution/validity_stability.py
1d0323fb080758156ee10f4f675bdab5acb990fe60bcd6963498b7577c9d7c3e  tests/fixtures/execution_lifetime_graphs.py
7ad289ec1617920e14ac2d797c2f44ec593a5a87a840f5210f4323b1cc69db5e  tests/unit/test_execution_validity_domains.py
62c85c6596b343c5e21d3ac9d5bc03550d9876b3fa9df80633bab5b0aaa9f758  tests/unit/test_execution_validity_stability.py
```

最终 output.log SHA256：`ec68191e970a056aff08c35f45b3e74c3e04e9cd8e60da28ebc19e15c3a7f67d`。owned 六文件现冻结；之后只做跨作者源码审查，不将自写部分当独立审查。
