已依 `docs/MODELING_SCOPE_AUDIT.md` 将已验证 expanded-call 与单接口 nested FunctionDef 能力受控接入 main。六个来源提交按顺序只应用生产 diff：`03d855e5`、`08b0b640`、`db2546b6`、`d892c7d3`、`8434f243`、`57911760`。每阶段逐文件字节前像、后像均精确匹配；13 个最终生产文件 SHA 与原交付收据一致，未整树复制。CLI、collector、pub/CI、其它 IR 内容及受保护 untracked catalog 未改。

main 普通消费实际 **exit0 / 25.691275 s**（GNU 25.86 s，RSS 182,084 KiB）：

| 原件 | ops | 结果 | 单项时间 |
|---|---:|---|---:|
| 旧 SP5 | 21 | 原 stored/decoded SHA、STRUCTURE、独立 Source/CodeWitness 均通过 | 1.173 s |
| Expanded-call（含 list build/extend→tuple） | 344 | 同上 | 13.107 s |
| Nested FunctionDef（单 semantic creation 接口） | 118 | 同上 | 4.555 s |

三个原件按类别和最小声明 decoded 大小机械选择；原 URI、namespace、七字段 receipt 保持。程序读取 stored 1,500,860 B / decoded 14,202,092 B。普通 owner/catalog 只做现 API 必需的元数据初始化及三个 entry 的 resolve/prepare，没有全 catalog export、planner/worker、source replay/lower、CodeType compile、target/raw、出版或 runtime binder。readonly 3 loads / 3 complete matches / compile0。13 源 SHA 与 protected catalog 前后不变；累计 metadata/source/program 的 stored+decoded I/O 未全计量，仍 OPEN。

函数创建保 defaults/closure/name/state/exception 的接口依赖，不增加子 body 执行或逐 bytecode staging 主图。旧默认/wire 兼容；新能力通过显式 AST 自动选择策略开启，CLI 未扩展。`REFERENCES.json` 固定原 18/7 delta 与精确 SHA，不复制原 program/provider/context 大 payload。

本次仅证明 main 三个代表普通消费者相容，不重授全部 25 项资格，不恢复 live owner，不增加当前 publication/runtime 覆盖。原失败/前沿、collector/runtime 条件及完整第一阶段 OPEN 保留。
