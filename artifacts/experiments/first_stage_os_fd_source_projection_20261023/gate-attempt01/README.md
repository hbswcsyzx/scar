# 唯一真实FD投影/全handle精化gate

实际exit0，73.74s、RSS296,208KiB，无代码修复/重跑。离线并行负载下的验收，不是
LeWM benchmark或加速。未执行target、compile、新Work生成或core改动。

8个必要raw档一次compressed读取/一次流式解压：82,093,008raw bytes、1,035,968行、
8,624,059compressed bytes完整SHA/bytes/lines核验。仅12,653行解析，生成12,649 FDports
（12,648 open输出+1既有OFD额外binding）及4birth facts；provider frontier0。

`result/manifest.json`为197,638bytes，SHA256
`0ebb957e8b4fd86eafefbce6f854ff045627cface9523f06766aabab8b2e8723`。
新provider共3chunks、27,655,358decoded/1,343,742stored bytes，不假冒旧R1 row。

- `all-port-selector-proofs.jsonl.gz`：12,649条，公开wholechunk有序读取，逐selector的
  table/chunk/ordinal/line/真实fd字段全部核；每chunk另实际combined_resolve一次，共2。
  不声称做了12,649次point调用或重复decompress。
- `all-handle-field-proofs.jsonl.gz`：12,684个实际same-ID handles公共codec往返及原/新
  非endpoint逐字段相等。35原provider原样保留；12,649新增provider的container仍Unknown。
- `birth-facts.json`：4个由原缺口自动得到的flags，3vfork+1真实CLONE_FILES clone3。
- `frontiers.json`：provider frontier0，creator无自身birth的actor frontier仍保留。
- `work-receipts.json`：原25selected Work与38access不变；原/新OFD target集合均12683。
- 原creator290个process=None不填数字TGID。未建继承/stdio与其它实际资源分母仍OPEN。
- producer/frozen-implementation/actual-imports记录实际源码：12关键SHA匹配，98当前
  SCAR源imports无漂移；未用其它source任务旧版本冒充。

`completion-receipt.json`单列实际exit0。所有原输入和旧producer不覆盖。
完整ExecutionModel与第一阶段仍OPEN，所需context进一步归属不是本门结论。
