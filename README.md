# 体育商圈滚动商户样本工作台

这是体育商业团队使用的本地业务工具，现有能力包括人工业务登记、状态核对、事务执行、变更追溯、可比增长分析和对外简报的联合披露控制。经营数据采用本地合成记录，不含真实个人资料，也不需要外部账户。现有业务操作见 `docs/业务约定.md`，当前不提供自动统计建模或自动经营决策。

可比增长分析把面板总变化分解为同店、进出、行业构成与营业天数效应：缺报不按零计入，拆并承接不产生新店增长，部分缺报单元单列而非悄悄剔除，结果只描述所选报送面板。披露控制按收件人联合检查阈值、集中度与跨期跨范围差分，被隐藏的单元格保留名称与原因；财务更正或承接修订后，未发出内容跟随有效分析，已发出版本保留并标识更正，订阅者可核对两版差异。

## 环境与运行

使用 Python 3.11，业务运行只使用标准库和内置 SQLite。测试与打包另需安装精确锁定的构建工具；Docker 镜像与冻结任务环境均在准备阶段安装它们，正式业务回放不访问网络。全部演示离线执行，写入用户指定的本地数据库；不指定数据库时只在内存中运行，不产生文件。

```bash
python3 -m pip install -r requirements-build.txt
```

```bash
python3 -m product demo
python3 -m product demo --db /tmp/merchant-panel.sqlite3
python3 -m product inspect --db /tmp/merchant-panel.sqlite3
```

业务数据的完整顺序保存在 `data/demo.json`（基础经营路径）与 `data/briefing.json`（赛事周可比分析、披露控制与更正版本链），`demo` 命令依次回放两者。也可将同格式的操作序列交给现有操作台执行，每项为业务操作名称与参数对象，不会隐式替换已有数据。

```bash
python3 -m product demo
python3 -m product replay --file data/briefing.json
```

## 测试与编译

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q product tests
python3 -m build --wheel --no-isolation
sh scripts/verify.sh
```

测试覆盖业务链、非法操作回滚、重复编号、变更历史、磁盘重启、增长分解恒等式、承接单元口径、联合披露隐藏与版本更正链。演示与测试的数据互相隔离，重复执行使用新的内存实例；持久库内的重复业务编号会被拒绝，不要在同一个库中重复导入演示。

## 容器

```bash
docker build -t merchant-panel .
docker run --rm --network none merchant-panel
```

容器仅运行本项目，不依赖旁路服务。常规测试和演示合计通常在数秒内完成；本地核验脚本 `scripts/verify.sh` 将演示输出放在临时目录并清理，运行预算为九十秒。后续新增功能也应保持小规模业务样本可快速复验，不要求预设统计方向。
