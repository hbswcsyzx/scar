新增 V7 自动 fixed-unpack targets 连接，复用同一 UNPACK_FIXED / UnpackShape 与既有 local、heap、cell/global store；无新 IR schema/协议/图权威。原 7 个失败 AST 中 4 个是 heap leaf，3 个是旧 local-only guard 拒绝的 Name。按两类各最高原调用权重、再 entry_key 机械选 2，未按库名/函数名选择。

同层 N 个结果先逆序 hold，按源左→右递归写入；heap helper 以 `rhs_held=True` 接收原结果，避免重复 hold。receiver→key→store 顺序和各自异常 post-world 仍走旧协议；已写目标不回滚，后续目标尚未求值时其结果引用继续保留。新 validator 核原 result Use→对应 store、NORMAL 顺序、原 source subtree、heap 正常释放 key/receiver/RHS；原 environment/heap/CFG/C0/C1 校验继续有效。原 capability/default 与 generator driver 字节保持。starred、target 内 BoolOp/IfExp/其它控制流、slice store 等仍留具体前沿。

真实结果：普通 catalog 全 243 candidates / 817 groups / 100438 calls 保留，worker actual exit0，267.178109s，readonly 2 loads / 3 complete matches / compile0。

| 原失败入口 | 本次结果 | 原历史权重 |
|---|---|---:|
| PIL/Image.py:805–815，两个 `new[...]` unpack stores | SUCCEEDED，92 ops；普通 STRUCTURE 与独立 source/CodeWitness reader 均 PASS | 78 |
| functools.py:553–598，Name/cell unpack | 113 prefix ops，停于 :587 Lambda；UNSUPPORTED、无完整 body/reader资格 | 1 |

只新增 1 个完整原 SP5（原 URI/七字段见 delta1），最新保存 UNSUPPORTED 46→45；其余 5 个原 unpack 前沿未重跑，不预填成功。Name/cell 路线只实测推进至后继 Lambda，不声称该类完整 body 已验。未扩 Lambda，未重跑全 catalog/目标；compile/raw/target/publication/current Run binding 均 0，78 历史权重不加当前 runtime。

SourceProgram 原 compressed 11,796,013B / decoded 100,896,994B 已被普通 reader 验过，本次交付不再解码、不重复入 Git。后续独立准入仍需原 source/code reader，不恢复已退出进程的 live owner。累计 I/O 未全计费、动态 dispatch/内容/对象同一/完整 effects 与整个程序完成度仍 OPEN。
