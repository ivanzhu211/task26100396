# crashgroup — Android 崩溃堆栈归组库

供 ResilienceForge 分析流程直接调用的纯 Python 库：输入报告与归组结果
均在进程内存中，无接口层、无磁盘 / 网络 / 外部服务依赖。

## API

```python
from crashgroup import fingerprint, group_reports

fingerprint(report_text)      # -> str，单份报告的稳定指纹（hex）
group_reports(list_of_texts)  # -> list[list[int]]，按语义相同分组的原始编号
```

- 指纹只由归一化后的崩溃语义决定，不随进程、批次或输入顺序改变。
- 归组结果中，组按首次出现排序，组内编号升序。

## 归一化规则

- 保留：异常类名（区分大小写，不改写混淆名 / 匿名类编号 / lambda 后缀）、
  完整方法帧序列（类名 + 方法名，含顺序与重复）、主因关系、
  每个异常直接拥有的被抑制异常（作为多重集，顺序可交换、重复次数不可丢）。
- 忽略：异常消息、文件名、行号、Native Method / Unknown Source 等位置说明。
- `... N more` 折叠行按语义展开为「直接外层异常完整帧序列的末尾 N 帧」
  （外层自身可再含折叠）；显式打印的相同尾帧得到相同指纹。

## 实现要点

- `parser.py`：缩进敏感（Tab 与 4 空格等价、可混用）的栈式解析，
  区分「Caused by 同级 = 直接主因」「Suppressed 深一级 = 被抑制」，
  折叠行的外层引用在创建节点时确定，与文本顺序无关。
- `seqhash.py`：多项式滚动哈希（mod 2^61-1）。折叠尾帧永不展开；
  所有「外层序列末尾 N 帧」查询按 N 降序扫描 + 并查集，近线性完成，
  可处理完整帧序列合计约 10 亿条的报告。
- `structure.py`：迭代后序遍历（2 万层主因链不爆栈），
  被抑制异常子摘要在父摘要前排序，实现顺序无关的多重集比较。
- 帧元素哈希只依赖类名 / 方法名文本（blake2b），与出现顺序无关。

## 测试

```bash
python3 -m pytest tests/ -q          # 全部
python3 -m pytest tests/test_perf.py -q -s   # 性能（打印耗时与峰值内存）
```

- `tests/test_grouping.py`：验收场景（消息 / 位置说明 / 被抑制顺序 /
  折叠写法不变，包装层 / 帧 / 重复次数变则拆组）+ 400 份随机报告与
  「完整展开后按业务规则比较」的参考实现分区间对拍。
- `tests/test_perf.py`：2 万层主因链（展开约 4 亿帧）与 2 万个不同长度
  共享尾帧（展开约 8 亿帧）两种规模场景，断言 10 秒与 256 MiB 预算。
