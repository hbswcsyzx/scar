# 任意本地包的静态值通路

这是 SCAR 之外的输入程序，不属于工具实现。包名和变量名都不参与规则。

```bash
conda activate lewm
python -m scar.cli import-values-v2 testcases/static_imports/program.py \
  --project-root testcases/static_imports \
  --out artifacts/reports/gates/g7-2a-import-example.json.gz
```

分析器应追踪 import、re-export、attribute 与两次 index，到达整数 `7`。
它不能执行最后的 raise。值路径的成立仍附 loader/cache/namespace 条件，
不能据此自动删除 import 的初始化，不能宣称已经修改程序或测得收益。
