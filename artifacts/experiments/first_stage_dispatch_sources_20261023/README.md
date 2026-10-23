# Production marker → 原 source invocation 实测

日期：2026-10-23。状态：本次引用连接已完成，**第一阶段仍 OPEN**。

## 输入与命令

- Source binding：`first_stage_source_bindings_reused_20261023/result`
- 原紧凑 bridge：`first_stage_joined_dispatch_20261023/result/native/dispatch-bridge.json.gz`
- 同一 capture：`first_stage_lewm_dispatch_20261023`
- 产品：`scar.analysis.dispatch_sources.bind_dispatch_sources`

```bash
bash artifacts/experiments/first_stage_dispatch_sources_20261023/run.sh
```

conda `lewm`，exit 0；wall **55.55 秒**，峰值 RSS **890,756 KiB**。
没有运行 GPU workload、测试套件、源码 compile/prepare 或完整 native graph 解析。
共同坐标仅重新核验原捕获的字节、manifest 与成员归属，没有重解析 native 图或
重新核验 RF correlation；source invocation 以流方式核验完整输出字节。

## 实际结果

计数单位为原 marker observation，同一次 invocation 可以对应多个 marker。

| 对应情况 | 数目 |
| --- | ---: |
| 原 marker observations，全部保留 | 79,592 |
| 匹配当前原 InvocationKey / CodeID | 79,112 |
| 有原 source definition 引用 | 28,448 |
| 有原 body / RegionActivation 引用 | 10,986 |
| 有 source 但没有已恢复 body | 17,462 |
| Invocation 存在，但 source 未恢复 | 50,664 |
| retained ancestor 缺失，逐条保留 | 480 |
| 根据已核 RF + 共同 Kineto artifact 接到原 native thread | 79,592 |

Source 输入的 **100,438 条 invocation、562,360,669 字节**全部流读，SHA 为
`e9e7741a68eba1683e4496cac8d7b8e02930f41a49746c974e1f7cf418c33113`，
与原 report 精确一致。source binding JSON 也按原 SHA/bytes 核验。
桥与 source 的 calls/codes/meta 原 SHA/bytes、进程身份和 Run 一致。

上游 **383 个未资格化 payload leaf**保持为原 bridge gap 引用。紧凑 bridge 没有
逐叶原描述，本适配器没有编造它们属于哪个 source port。已有 109,288 条逐槽关系
仅作为原 bridge path indices 引用，没有重新建立 producer 或声称 logical version。

## 可查询产物

```text
result/
├── associations.jsonl.gz
├── marker-index.json.gz
└── report.json
```

每行仅保存原 marker instance/raw ref、原 source invocation/binding 行引用、
原 definition/body/activation 引用、已核 native thread 引用与缺口。

```python
from scar.analysis.dispatch_sources import query_dispatch_source

row = query_dispatch_source(output_directory, original_marker_instance)
```

`query-results.json` 保留四种状态的实际查询结果：BODY_LINKED、SOURCE_LINKED、
INVOCATION_LINKED 和祖先缺失。索引与所选行 hash 均在查询中核验。

## 证据边界

- 全部关联始终为 **RETAINED_ANCESTOR_CONTEXT**，没有升级成 direct Python/ATen call。
- native TID 仅在原 bridge 已核 RF 对应的观察上使用，同捕获的 Kineto artifact
  经 `coordinates.thread_for(..., "linux_native_tid")` 解析；没有全局等同 Python ident
  与 Linux TID。
- 原 source producer 的 `reused_code` witness 条件、当前 raw-scan 收据和未知项继续保留。
  本步骤核验 source 输出全部字节与 capture 身份，没有再逐条重放原 call raw parser。
- 未闭合 actual/formal、返回值、环境、状态、副作用或 ready/lifetime。
  没有新建规范图、producer、优化规则或变换，不能据此宣布第一阶段完成。
