# crashgroup

Android 崩溃堆栈归组库（纯内存，无接口层）。输入为已去除 logcat 前缀的
JVM 异常文本，输出稳定指纹或分组结果。

## 用法

```python
from crashgroup import fingerprint_report, group_reports

fp = fingerprint_report(report_text)            # 单份报告的稳定指纹
groups = group_reports([(rid, text), ...])      # 批量分组，返回 [[rid, ...], ...]
```

## 归组规则

指纹只由崩溃语义决定：异常类名、完整方法帧序列（`Class.method`，区分
大小写）、主因关系、被抑制异常多重集合（同层可交换顺序，重复次数须
一致）。忽略异常消息、文件名、行号及 Native Method / Unknown Source。
`... N more` 折叠尾帧按“直接外层异常的完整帧序列末尾 N 帧”语义解析，
与显式打印的相同尾帧得到相同指纹；折叠帧通过多项式滚动哈希 + 倍增法
符号化求值，不做展开，可处理合计约 1e9 条逻辑帧的报告。

## 测试

```bash
python3 -m pytest tests/ -q                 # 正确性 + 模糊测试 + 性能测试
python3 -m pytest tests/test_performance.py -q -s   # 查看耗时与峰值内存
```
