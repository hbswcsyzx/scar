# 真实LeWM原生内存生命周期导入

2026-10-22，产品7bcece2。第一阶段OPEN。

## 命令与范围

run.sh通过公共`scar import-native`导入未修改LeWM此前成功episode的ETO/Kineto原档，
保留准确provider revision及原始字节hash。完整输出result/；未另跑目标或增加测试。
运行exit0，wall299.59s，peak3476296KiB。

## Observed

| 项目 | 数量 |
| --- | ---: |
| 原memory记录 / 逐项保留 | 70872 / 70872 |
| 分配代次 | 35598 |
| 配对释放 | 35274 |
| 窗口末仍open | 324 |
| 地址槽 / 发生复用的槽 | 4581 / 916 |
| 未匹配free / 不明确birth | 0 / 0 |
| CPU / CUDA记录 | 11198 / 59674 |

运行独立标准库audit.py：PASS，见audit-result.json。它直接重算原档地址历史、
完整记录分母、代次、raw locator、final ValueGraph hash及LIVE/RETIRED对应，不调用
产品importer算法，也不加载完整evidence bundle。每个allocation绑定最终graph hash，
不会用地址复用混淆不同分配；窗口末open不能推为泄漏。

## 仍未完成

旧采集没有experimental_config.adjust_timestamps字段，不能推定False。
70872条生命周期声明均CONDITIONAL、ordering_qualified=0。已验证原生receipt
关联，未建立物理cudaMalloc/free、Tensor内容/逻辑版本、canonical stage/effect
对应或完整ExecutionModel。沒有优化授权，也没有完整模型结论。

新采集入口显式请求adjust_timestamps=False并记录是否成功；下一次完整LeWM
采集同时补函数环境actual，复用一次运行，旧档保持原样。
