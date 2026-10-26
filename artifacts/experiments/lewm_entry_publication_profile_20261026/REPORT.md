Root确认session53184实际exit0。whole231.408548s；GNU232.19s、peak1,219,520KiB。正常plain858/project、原continuation、同3readonly archives和catalog为genuine owner；仅机械选择原首个SUCCEEDED SP5。没有降低原normal检查、lower/compile/target、publication或current369749绑定。

setup单列：wall141.570613s；其CPU见setup.json，不能摊入后续profile。原SP5正常reader一次（stored2,555,042B/decoded21,830,386B），archived text由真实catalog.prepare取得。

| cProfile阶段 | wall(s) | CPU(s) | 实际input delta |
| --- | ---: | ---: | --- |
| 同project source_inputs首次 | 0.987970 | 0.986136 | 0 |
| 同project source_inputs重复 | 0.966690 | 0.965139 | 0 |
| 原SourceProgram.read_structure一次 | 79.986235 | 79.831442 | 0 |

结构phase145,879,372次函数调用：validate_source_program累计58.3891s；record_errors累计56.9192s；_record_errors累计55.7336s/递归14,483,654次、自身30.2691s；is_dataclass11,792,964次/累计11.5111s、自身7.4666s。mapping_errors累计43.8219s、validate_source_control_flow累计38.1614s。这些是嵌套累计时间，不能相加；cProfile显著增加Python调用成本，不能将79.99s当未profile耗时，也不能直接除以原约37s或外推全26占比。

结论：指纹每次约0.98s的重复成本确实存在；结构验证有大量递归/反射成本，不能把原每条37s全部归给canonical。应先做保持类型、nested mutation、post_init与错误路径的validator局部快路，再以同一真实条目的可比证据决定是否需要静态source snapshot复用。

I/O总2,942,500,315B，pending0/无预算拒；metadata/graph/code分桶见RETENTION.json。source/control SHA另25,071,720B。注意final meter的read_structure phase label包含profile后原静态闭包检查2,301,432B；真正被profile的read_structure actual_input_delta={}，其余两profile也为0。136实导入SCAR模块全部属于main冻结371源。

本结果是有限性能诊断，未使64946的9个CP2生效，不建立新body/source/值/state/ready资格。未输出Tensor值、locals、源正文或graph/model。原失败门与本门冻件不改。
