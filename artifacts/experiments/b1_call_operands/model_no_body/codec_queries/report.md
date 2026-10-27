# D2.2 wire / queries / CLI 子组件报告

## 结果与范围

**Implemented / Verified（定向结构测试）：** 本任务授权的 wire、只读查询和 CLI 汇总已完成。首次且唯一 pytest 运行 **45 passed in 1.71s**，exit 0；harness 总耗时 2.318s。运行环境为 conda `lewm`、CPython 3.14.7。未运行 full、LeWM、GPU 或新 runtime capture，未测性能或加速比。

精确命令：

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m pytest -q tests/unit/test_program_no_body_codec.py tests/unit/test_program_no_body_queries.py
```

完整 stdout/stderr 合并输出在 `initial.log`；命令、解释器版本、退出码、耗时和测试前 8 个授权文件 SHA-256 在 `initial.json`。`format.pretest.json` 记录相同文件的 AST 解析与单一终止换行。依赖/fixture/golden 指纹另在 `source-manifest.json`。首跑无失败，无后续 pytest 重跑。报告生成脚本曾因未激活 conda 找不到 python，原消息保存于 `report-generation.attempt1.log`，不涉及测试或产品变更。

## 已落实的连接

- schema 最大版本 13，只有 `created_close_tests` / `no_body_finishes` 任一非空才选择 v13。未发布 SessionUpdate、reference-drop 或 F/P 数据表。v13 必须具备实际能力；v1–v12 拒绝夹带任一新顶层字段，即使值为空。
- v2–v12 历史 frozen payload 均逐字节重编码相等；v1 迁移轮廓验证旧字段严格性。独立 v12 golden 由 root 从 immutable `e86563a7f1b729549e73078f3776f715a9a9edec` 的 schema12 codec 生成；当前 `publication_program(target='value', extra_domain=True, strict_subset=True)` 也直接等于该历史 payload，覆盖抽取 `with_publications` 的实际 fixture 回归风险。三个既有 codec 测试仅最大 schema 常量改为 13，原 document wire 10/11/12 断言保留。
- `created_close_test` / `no_body_finish` 返回原记录；`CreatedClosePredicate` 返回原始 role UseSite、bool DataValue、真实 BRANCH condition 及第 0/1 条实际 successor；`NoBodyPublication` 返回真实 true-edge finish、owner UseSite 和原始 StateAccess/before/写后值。查询不制造新 producer、不求值判定、不复制当前状态。
- BODY 与 ASYNC_REQUEST、direct-owner / entry-copy、readonly test、strict-subset write 域均有用例；显式 `RequestAssociationRead` 的 NORMAL body/E 端口按 canonical Use 连接，scheduler S 和 effective E 保持独立 Use。
- CLI 在完整 validate 成功且存在 lifecycle scope 与本门能力时，才报告 `no_body_structure_validated`。predicate-only 记录 finish count 为 0；无新能力旧图与非法图均不授该结构状态。lifecycle / source / runtime / transformation 权限仍为 false。
- 非法 false-edge finish、漏 lifecycle scope、额外 proof 字段、未实施表、嵌套私自篡改的 bool successor index、降版本等均被拒绝。

## 明确未授予的结论

本报告只验收本子组件的序列化、canonical 查询与 CLI 结构接口。手工 fixture 不证明 Python/CPython close 条件或真实 family adapter 适用，predicate 条件仍需执行器/provider 证明；不声称 D2 全部结束、session/drop 已实现或可自动优化 LeWM。graph validator / records / fixture 为并行任务交付，此处只使用其 root READY 后的冻结版本。

## 冻结

pytest 结束后未修改 tracked 产品或测试；只补 ignored 报告与指纹。没有提交、推送、安装或环境变更。
