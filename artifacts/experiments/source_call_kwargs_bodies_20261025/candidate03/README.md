# candidate03：显式归档文本 readback；首图复用、余三项 lower

仅新增第12生产文件的窄API：SourceProgram.read_structure/from_dict→validate_source_program
以STRUCTURE专用source_texts dict[str,str]传给原semantics/control validators.sources。wire不变，
SOURCE_REPLAY提供该参数明确拒绝；None默认兼容旧行为。两个原validator对缺key直接拒绝，
不回退live文件；未monkeypatch文件或跳过校验。program_lowering.py SHA
c1d0a8a3204aff994933e957c8fdcfbab6e07300a6a9ee2ef257ed4446ab250d，其余11源码未变。

已有92ops图+准确原UTF8的小readback已通过（6.171959s，guard physical+decoded6801460B），
旧producer freeze/旧reader SHA和新reader SHA分列。没有重lower或新CodeWitness资格声明。
本次保留原artifact逻辑URI，不复制成新producer图；fresh owner重新核旧输入/subject/code/context、
正常新CodeWitness与原图的结构/AST/compiler/pending。新lower序列由原AST谓词集合减去准确
复用项机械得到5/10/12，首项4只复核92ops图，不进入session.lower。

freeze `500187b4d9aede9184573cff0b0f55a0d5ff7812a21f78091d1ee57cb2573d4a`；352候选源码/12必要源码/24准确输入，21原输入完全未改，新增旧92ops gzip、
旧producer freeze和旧body输入。main与iso旧artifact都按准确URI白名单进入guard，实际physical/
gzip decoded每次读取都计256MB；原96MB composition、64MB context/record、输出256MB、
180s/body/600sworker/660souter、4000ops/body/总16000、20sheartbeat均不变。复用额外输入占预算，
不足即FAILED_RETAINED，无自动调大/重试。新emitted计数不包含旧92ops；失败时已经返回的
emitted cost保实际数，只有进入lower却未返回才UNKNOWN。

root持有一次新session：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/zyf/AAA/scar-worktrees/source-call-model /home/zyf/miniconda3/envs/lewm/bin/python -B /home/zyf/AAA/scar-worktrees/source-call-model/artifacts/experiments/source_call_kwargs_bodies_20261025/candidate03/run_gate.py --execute --freeze-sha256 500187b4d9aede9184573cff0b0f55a0d5ff7812a21f78091d1ee57cb2573d4a
```

固定fresh candidate03/attempt03，当前不存在。普通结构、原AST/compiler、局部pending分列；
非默认filesystem SOURCE_REPLAY。CALL_EX局部unwind/outer-prefix及整体语义仍OPEN，无publication、
current Run整合或新episode。candidate01/02 runner、freeze、失败及92ops原档都保留。
