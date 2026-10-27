# R2.1 冻结与有限实档核验

2026-10-23：先AST/source冻结，再按授权运行一次35port有限gate；无目标或测试套件。

已实现三个typed record、独立ProviderResourceAccessID、原ExecutionModel的一个新关联
表、executor/handle union、ProgramGraph28/Execution9版本门控，以及原R1之上的窄只读
selector/refinement adapter。canonical access和State体系保持原义，无fake ProgramSnapshot。

`static-freeze.json`保存实际HEAD、11个代码文件SHA/bytes、文档与原R1 manifest收据；
`implementation.patch`保本次源改动（含新adapter）。原R1 producer/681chunks不变。

`gate-attempt01/`保留原35个declared producer ports与3个已知executor实档差量gate。
公共API：OSResourceBase.selector/resolve、build_os_resource_refinement、
OSResourceRefinement.read/record。只扫描observations一次，原work做有界point read，
不重跑22分钟CLI，不实施INPUT/shared FD/VM/ancestor算法。

35ports/22work/13pipe/3executor与有限codec检查已完成；原进程随后footer metrics变量
shadow报错exit1，独立小finalizer核已存收据后exit0。没有重跑gate，详见该目录README。
完整模型仍OPEN；有限端点核验不表示完整ExecutionModel或新ProgramGraph正向组装通过。

root独立stdlib审核`root-audit.py`：134个准确selector按原chunk分组读取，仅核需要的
chunk双层SHA/行数/ordinal和preimage；全部35端点、22producer work、13pipe双端及
3executor原目标/点/线程核对exit0，3.08s、RSS98,328KiB。未import SCAR、未重扫百万
observations、未执行完整model validator。`root-endpoint-audit.json`保存结果。
首次root审核错误使用不存在的name字段而退出，原脚本/日志/time保留；按实际R1
record的syscall字段修正后attempt02通过；原base/delta未改写。
