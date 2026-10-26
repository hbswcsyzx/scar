先不改生产。当前`_validation.py`已经缓存_type_plan、_dataclass_schema和type hints；不要再重复提出同一缓存。现值/校验结果不缓存，mutable IR仍每次遍历；这个边界应保持。

1. 优先：exact builtin primitive成功快路（仅_validation.py）。INT/FLOAT仍保exact int、bool排除及原float接受规则；成功的exact str/bool/None等builtin值可在既有类型匹配后直接返回，避免落入is_dataclass。遇subclass、dataclass类/实例、PythonLiteral或自定义类型保持原fallback，PythonLiteral preflight不跳过。现profile的is_dataclass达11.79M次/自身7.47s；预计可实测证据是该调用数和primitive叶节点成本下降，不承诺全门加速数。

2. 可与1小合并：schema-only record plan的exact-class分派（仅_validation.py）。缓存的是声明类型是否为dataclass及字段计划，绝不是record的值/成功结果。type(value)恰为声明class时可直接使用已缓存schema；subclass/特殊typing/dataclass-class值走现路径。每个field仍实际遍历，__post_init__按原无子错误条件逐次执行，nested mutation仍重新查；不缓存post_init函数（以免改变运行时方法选择）。若类schema可变性超出当前_hints/_dataclass_schema既有合同，保fallback。预期看反射调用下降，14.48M递归中的实际字段检查数量不得因值缓存消失。

3. 仅在1/2实测后仍有显著self成本时：内部error accumulator，保公开record_errors的新list返回（单文件较大hunk）。dataclass/container字段仍按原顺序遍历、相同path和全部错误；用局部起始offset决定是否调用该record的post_init，union每branch隔离错误并保原尝试顺序。这样可减少每叶[]与empty extend；不能借它略掉嵌套检查、改变union错误或post_init副作用。此项风险高于前两项，不建议先一次性混入。

建议先授权1（必要时2）最小差异，保所有原CFG/source验证和reader默认，不做全局/裸id memo、不新架构。验收用已有validator测试，另一个很小的前后同输入结果比较覆盖：bool当int、mutable及nested非法修改、dataclass subclass/类值、PythonLiteral、union失败path、post_init失效。只针对实际改口，不扩矩阵；随后同一原SP5的结构诊断须同时看有效性、recursive/reflective调用数和wall/CPU，cProfile只做可比指标不能冒称生产speedup。若仍需source_inputs复用，再单独审不可变snapshot/受控epoch；不提前绕过77.6MB document完整性/CAS。原全部26全门及独立factory/query保留，wall/名单不改。
