# D2.3 codec / records 集成报告

## 有限结论

**Implemented / Verified（结构与 wire 定向测试）：** schema14、两张新表和已有 canonical 图的严格序列化已经完成。首次且唯一 wire 定向运行 **40 passed in 1.89s，exit0**。records 的独立终态为 **27 passed in 0.35s**，其首轮测试隔离错误及修正完整保留于相邻 `records/`。未运行 full、LeWM、GPU、新 capture，未作加速结论。

本任务拥有并已冻结：lifecycle.py、model.py、program/__init__.py、codec.py；两个新增测试文件；四处历史测试中最大 SCHEMA_VERSION 常量13→14。其他 graph validator / fixtures / query / CLI 为根代理所有，本任务未修改。

## wire 合同

- ProgramGraph 仅追加 `session_updates` / `terminal_frame_releases`；两表任一非空选择 v14。没有提前加入 session/finished 派生事实或 release 许可表。
- v1–v13 严格拒绝两张新顶层表，包括空表。v14 必须有真实能力，缺表、额外字段、降版本不能悄悄丢记录。无新能力保持旧 schema；v2–v13 frozen wire 逐字节重编码相同，v1 迁移轮廓按原规则检查。
- 独立 v13 golden 由 root 从 immutable `817cc0ba082d7dbc5c2f97bb9049cca1056466f4` 旧 schema13 codec 生成，89825 bytes，SHA256 `b833f028476a379e4c178fcfc7ad33d5dfebf2f7423df51593c871589139e6b6`。除 loader/reencoder 比较外，当前 `no_body_program(target='value', extra_domain=True, strict_subset=True)` 直接等于该历史 payload 的断言也已通过。
- AFTER_OPERATION / NORMAL_COMPLETION × HOLD / COMPLETE / ABANDON 六组合，在 L/D、W/L 不同的 fixture 上 roundtrip；Return/Raise/no-body、Suspend 不带 release、两个实际 release 尝试亦通过。两表各自独立能力可 roundtrip，所有 Value 的原 producer 保留。
- 新 source 元数据不制造 actual/state/producers。wire 拒绝 runtime_verified 字段、R/B 共用一个 UseID、修改固定 FrameRules、nested bool/enum 私改。破坏性测试使用独占 FrameRules，不污染默认对象。

## 实际命令与证据

```bash
source /home/zyf/miniconda3/etc/profile.d/conda.sh
conda activate lewm
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m pytest -q tests/unit/test_program_session_release_codec.py
```

CPython 3.14.7。`initial.log` 保存完整 stdout/stderr；`initial.json` 保存解释器绝对路径、精确命令/cwd、退出码、耗时及测试前10个授权文件 SHA。运行前已检查 AST 与每文件单一终止 LF；`source-manifest.json` 额外记录 fixture/golden 指纹。wire 首跑无失败，无重跑。

## 不授予的结论

本报告不验收根代理的完整 E/F/T/P 算法、实际 native family/helper 条件、runtime/source 对应、frame 所持引用或物理 free，不宣称 full D2/C2 完成，不授权程序变换。NORMAL_COMPLETION 仍为适用条件未证的后置声明；TerminalFrameRelease 固定 UNKNOWN / MAY_NOT_COMPLETE / UNRAISABLE / NOT_GUARANTEED，不产生消耗权利。小型自写 IR 测试不是 Python 运行时 adapter 证明。

pytest 终态后未修改产品/测试，仅补 ignored 报告和指纹。未提交、推送、安装或改变环境。
