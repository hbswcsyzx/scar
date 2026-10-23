# 第一阶段：数据挂载恢复后的真实 LeWM 全流程采集

状态：**Observed：成功 episode 和原始证据已取得；完整建模 OPEN。**

用户告知历史输入已挂载后，使用现有 conda `lewm`、原 `run_inference.py` 和原
pusht checkpoint 执行 [run.sh](run.sh)。SCAR 产品版本 `7de08ee`，LeWM
`f70fed80288462ca4d006cb3607ec6da6eaa851f`；before/after Git 状态均为空。
没有修改目标、依赖、Torch、CUDA 或共享缓存。

```bash
python run_inference.py --config-name=pusht policy=pusht/weights.pt \
  eval.num_eval=1 eval.eval_budget=25 eval.goal_offset_steps=25 \
  cache_dir=/gpu4-share/data/byx/lewm_data hydra.job.chdir=False
```

完整启动还由通用 SCAR call/operand/environment、ETO/Kineto 和 strace collector
包装，具体参数见脚本。没有按业务函数名选择或写优化规则。

## 实际结果

| 项目 | 结果 |
| --- | ---: |
| 返回码 | 0 |
| 插桩墙钟 | 291.930766s |
| 目标记录的 evaluation time | 48.236336s，仍含插桩 |
| episode | 1；success=True，结果及 `env_0.mp4` 已保存 |
| Python 调用 | 86,206 invocation / 172,412 event / 852 code |
| call drop/error/open | 0 / 0 / 0 |
| call completion 未定 / 挂起 | 65 / 4,021，未伪造正常返回 |
| 函数环境 | 12,334 dispatch / 4,069 entry，0 drop/error/gap |
| 环境当前待匹配 / 丢弃未匹配 dispatch | 0 / 8,265，丢弃不表示完成绑定 |
| provider | Torch 2.13.0+cu132，CUDA 13.2，RTX 4090 |

原始 profiler 显式 `adjust_timestamps=false`，未保存 Tensor 内容或用 `_version`
证明不变。环境 identity/reference 不等于逻辑值版本或纯函数证明。采集只覆盖
声明进程/线程窗口；一次成功运行不证明其它配置或未执行分支。

## 后续导入

同次原档经公共 `import-capture` 自动核验并共同构造执行身份，见
[联合导入](../first_stage_joined_capture_20261023/README.md)。机器产物保留所有
已知未连接义务。以上时间不能用于最终性能比较，本轮没有变换或加速比。
