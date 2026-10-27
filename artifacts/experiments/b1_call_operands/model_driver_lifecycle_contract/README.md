# D2.0字段及派生规则的收敛证据

2026-10-18；设计基线38d2968。**PASS_DESIGN，不是D2产品验收。**
实际规范为docs/M1_DRIVER_LIFECYCLE_CONTRACT.md；contract.frozen.md是本次受审版本快照。

## 收敛结果

- body-only publication的W⊆L⊆D与实际source/owner/current-state唯一来源；
- NoBodyFinish使用实际bool/BRANCH真边，false不制造异常；核心edge0真/edge1假，
  不在overlay另存可冲突polarity；
- SessionUpdate两种绑定、当前版本失效；固定body-only intrinsic可保持已有session谓词，
  不声称world相等；
- 窄TerminalFrameRelease与真正raising wrapper分开，不造一次性权利、不授stillheld/free；
- E/F有限must分析先沿每条边同时改名再join，先稳定布尔解再求解释来源T。
  不枚举执行配置，不把来源和owner分别union后配对；F与当前P不同。

## 证据分母及原建议

review/三份合同报告和两份终审保存原建议与root裁决；owner_flow报告另保存收敛审查。
被撤回的一次性unused窗口、overlay真边索引以及联合来源单调性论证均在原文说明，
不能用修改后的结论冒充初稿本来正确。初期两份review绑定的是合并合同较早hash；
root之后补充pending的适用条件与E/F→T两阶段，owner终审核对最终hash，receipt保留差别。

owner_flow.py是stdlib方程harness，没有import产品或工作负载。首次误用系统Python3.12.3
的命令/输出/hash保留；按用户环境要求，对相同冻结字节在conda lewm Python3.14.7
仅运行一次，11场景、1,920有界单步检查通过、0.12s。320组固定seed抽样来自1,728
有限concrete状态，不是穷尽证明；两次不合计独立覆盖，loop样例不代替两阶段收敛论证。
未运行新LeWM/GPU或全仓。后续D2.1产品实施/组件与冻结回归在独立model_body_publication归档。

验收只关闭D2.0声明字段与派生规则设计；NoBody/Session/drop及E/F/P仍按D2.1–D2.4
逐门接到产品。D3实际native条件、全family和完整M0–M2仍开放，没有新LeWM加速比。

只读核对已保存证据，不运行harness或产品：

```bash
conda activate lewm
python artifacts/experiments/b1_call_operands/model_driver_lifecycle_contract/check_evidence.py
```
