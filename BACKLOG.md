# BACKLOG.md — 待办与进化项池

> ROADMAP 项见 ROADMAP.md。此处记录 EVOLUTION LOOP 自驱进化项。

## 第 1 轮进化项（按优先级）

### A. 质量
- [ ] E1.1 补 fetcher.py 边界测试（429 退避、timeout 重试、FetchError 路径） [S]
- [ ] E1.2 补 cli.py cmd_run 路径测试（mock fetch + 断言输出） [S]

### C. 评分精度
- [ ] E1.3 跨源去重：同标题多源报道只保留 authority 最高者 [M]
- [ ] E1.4 扩展 penalty_words（更多标题党词） + 测试 [S]

### D. 鲁棒性
- [ ] E1.5 runner 单源失败不阻塞 + sources_failed 准确计数 [S]

### E. 可观测
- [ ] E1.6 cli report 增加 7 天推送统计 + 源成功率 [M]

### F. 体验
- [ ] E1.7 飞书 card 模板 A 级条目高亮（不同 template 色） [S]

## 已完成

_(空)_
