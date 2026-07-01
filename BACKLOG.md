# BACKLOG.md — 待办与进化项池

> ROADMAP 项见 ROADMAP.md。此处记录 EVOLUTION LOOP 自驱进化项。

## 第 1 轮进化项（已完成 ✅）

- [x] E1.1 补 fetcher.py 边界测试（429 退避、timeout 重试）— 覆盖率 76%→97%
- [x] E1.3 跨源去重 dedup_cross_source — 同标题多源保留 authority 最高者
- [x] E1.4 扩展 penalty_words（标题党词）
- [x] E1.6 cli report 7 天统计 + 源成功率
- [x] E1.7 飞书 card A 级高亮 note block

## 第 2 轮进化项（进行中）

### A. 质量
- [ ] E2.1 补 feishu.py/dingtalk.py 错误路径测试（提升 80%→90%+） [S]
- [ ] E2.2 补 cli.py cmd_run/cmd_collect 路径测试 [M]

### B. 源覆盖
- [ ] E2.3 新增安全/设计类别源到 feeds.yaml [S]

### E. 可观测
- [ ] E2.4 源健康度：成功率统计 + 自动降权逻辑 [M]

### F. 体验
- [ ] E2.5 钉钉 markdown 分级折叠（A 级在前） [S]

## 已完成
- 第 1 轮全部项（见上）
