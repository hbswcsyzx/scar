# SCAR

State · Control · Action · Resource：通过程序依赖图支持自动化简。

当前只开发第一阶段：**静态建立共享子图，动态补充实际实例和绑定，接通跨层依赖**。
第一阶段尚未完成，不启用目标程序变换，也没有 LeWM 加速比结论。
形式前端逐层验收：声明材料的F0/F1/F2、F3-A、F3-B和C1源码上下文路由已通过；下一项是C2词法名字接口。
LeWM 是外部 testcase；通用规则不按业务名称选择处理方式。

## 使用

```bash
source ~/miniconda3/etc/profile.d/conda.sh
conda activate lewm
cd ~/AAA/scar
python -B -m scar.cli static /path/to/program --out /path/to/model --phase bodies --jobs 4
```

静态入口不导入或运行目标。按需 CALL 采集和离线连接用法见开发说明。
已有函数/循环展开、跨分片依赖查询、有限属性推理；存在节点不代表依赖或效果已闭合。

## 文档

- [模型](docs/MODEL.md)：实体、身份、边、可展开结构与正确性约束。
- [流程](docs/ARCHITECTURE.md)：形式前端、建图流水线及动静分工。
- [开发用法](docs/DEVELOPMENT.md)：命令、查询接口和工作区约定。
- [当前状态](docs/STATUS.md)：真实结果、缺口与下一步。

当前权威图在 `artifacts/current/static/`；原 trace 与派生查询证据在
`artifacts/current/queries/`。大产物不提交 Git，只保留一份正在开发的源码。
