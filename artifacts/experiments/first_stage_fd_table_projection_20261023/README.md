# 单次非target OS原档补集投影

实际exit0，0.99s，RSS43,076KiB。输入为既有369749 capture，**未重跑target/采集/原导入**。
未修改任何生产IR、adapter、coordinates或原R1/R2产物。

252档全部双SHA核验：9,264,445decoded bytes，36,665行；36,664 completed calls+1signal。
保留78条context事件，无unfinished/resumed、leader migration marker、必须字段或相关
argument rendering缺口。非target exec31=6success+25failed；与精确绑定原R1全scope
32=7success+25failed作差，target只含既有初始成功exec一次。

35/35既有端口现在具备container精化条件；**实际精化0，原R2仍35个Unresolved**。
完整ExecutionModel/第一阶段仍OPEN。下一步实现须根审查，未在这里启动。

- `project.py`、`run.sh`：实际入口；现有输出以`x`拒绝覆盖，勿直接重复运行。
- `producer.json`：运行前脚本/模块SHA与revision `b2c6ed5b167b89afb04e0c7a339174a44cfd9164`。
- `file-receipts.json`：全部252档原archive/coordinates receipt、真实行与call分母。
- `context-events.json`：78条相关原行及生存/线程组归属证据。
- `summary.json`：完整scope/counts作差/预算/前沿；并非container实施或全模型验收报告。
- `run.stdout.jsonl`、`run.stderr.txt`、`run.time.txt`：唯一实际运行记录。
- `artifact-receipts.json`：以上小产物的最终SHA，不复制原raw或大表。

严格证明条件和类型边界见`docs/FD_TABLE_PROJECTION.md`。
