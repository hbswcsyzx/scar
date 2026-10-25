# 四 body kwargs 有限门：已准备、未运行

入口目录仅在 source-call-model 隔离树；11个生产源码保持 implementation receipt的原SHA。
`selection.json` 由原12项诊断的 Call/**/无* AST谓词机械筛出4项（sequence4/5/10/12），
当前 report.inventory 与 coordinate_binding 已准确核小metadata receipt；两个准确原分片中
定义/source/context相同且各body仍UNSUPPORTED。源码AST重核来自两份原UTF8。context、
composition JSON和marshal payload均未在本准备过程展开；只冻结其physical SHA/stat与声明。

freeze SHA：`936968d032a1ac74e2716427ee30140febfdadfc06e28e183da1d862944becac`。
freeze包含352份候选SCAR源码、11个必要修改源码、runner/guard/preparer/selection、Python/GNU-time
及21个准确原输入。参与源码在实际run前后核SHA，actual imports须来自本隔离树。原数据运行前后
核stat；实际公共reader+guard在读取时核physical SHA与gzip EOF decoded字节/SHA，不为冻结终检
重复扫描大原档。准备阶段的原数据物理哈希读取成本不冒充真实门的输入成本。

两个composition roots分别为stored17035096/declared decoded77169599B与其必要原parent
stored17026103/declared decoded77109809B，均独立96MB cap；不是把ISIZE当SHA。
两个context分别声明5482298、14109925B decoded，仍64MB cap。
21项unique stored为37877152B、unique gzip declared decoded为177532748B；此215409900B
仅是已冻结输入的声明基数，不是实际读取成本。真实CompositionIndex会复读parent原档，
SourceCodeEvidence也可能复读组件；guard把每次physical读取和gzip解码都计入256MB总额，
超额即FAILED_RETAINED，不缓存/隐藏重复读取、不自动调大或重试。

限额：4 bodies/2 source files/4000ops每body/总16000；每body180s覆盖证据与context设置、lower、
公共结构和独立检查，共享composition设置计入worker600s，outer660s；input/output各256MB；
context/单输出record64MB。20sheartbeat、GNU-time与SELF RSS分别报告。输出还累计压缩JSON的
decoded representation及公共回读stored/decoded量；失败保留BUILDING、已写metadata/图、日志。

compile/exec/prepare有实际guard和计数：禁止目标CodeType执行/可执行编译、live源读取、新source
prepare/rebuild以及main写入；CodeWitness只读，compile_attempts/source_bytes_read必须0。
AST-only parse与symtable分析单独计数，非目标producer/library编译audit也单列，不伪称所有Python
import都没有compile。实际动作通过才可报告target executable compile/prepare/target=0。

SourceProgram public STRUCTURE回读、准确归档AST+正常SourceCodeEvidence/compiler核验、
call-owned pending各自保存。默认metadata.source.path文件系统SOURCE_REPLAY不运行，不把
结构结果/metadata PASS冒称source proof。CALL_EX局部unwind合同、outer prefix及整体lifetime
仍未证。原sequence12的同span Expr frontier不能当Call atom；实际run按ASTkind/span/fingerprint
重新取唯一SG Call atom/operator/output，并同时保留原Expr前沿来源。

root审核后持有一次session运行：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/zyf/AAA/scar-worktrees/source-call-model /home/zyf/miniconda3/envs/lewm/bin/python -B /home/zyf/AAA/scar-worktrees/source-call-model/artifacts/experiments/source_call_kwargs_bodies_20261025/run_gate.py --execute --freeze-sha256 936968d032a1ac74e2716427ee30140febfdadfc06e28e183da1d862944becac
```

固定fresh `attempt01/`；完整窗口报告`attempt01/result.json`，逐body输入/返回/图/检查分开。
任何validator异常为FAILED_RETAINED，不能归为UNSUPPORTED；未返回body的emitted cost为UNKNOWN。
窗口exit0也只代表4个返回记录处理完，需逐项看graph/new frontier；不作publication/current Run
整合、全程序PASS或新episode声明。当前attempt01不存在，未启动任何真实body门。
