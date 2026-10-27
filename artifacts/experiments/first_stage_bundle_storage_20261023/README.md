# 真实留存IRBundle：分块存储往返

2026-10-23，**Verified / PASS**。只读取此前已成功CPU目标的原档，不执行目标、
forward或额外测试套件。

`run.py`经现有native/dispatch/physical importer得到原bundle，新writer直接逐记录
保存；reader逐表校验原record、顺序、数量及chunk stored/decoded SHA和locator。

- 25表、786条原记录逐条相等；8 chunks。
- decoded914,170字节，stored52,977字节；manifest9,031字节。
- 原39个物理Tensor槽保留；没有生成LogicalVersion或优化权限。
- 脚本、base revision、模块SHA、time、progress和逐表摘要都在本目录。

这是CPU原档的真实存储验收，不代替完整LeWM/GPU联合模型验收。
