# InfoDigest

> 轻量、零运维、可自托管的开源信息聚合器。基于 RSS 的信息收集系统，完成采集、去重、规则评级、模板排版（不依赖任何大模型），并定时推送到飞书 / 钉钉，通过 GitHub Actions 部署与调度。

![CI](https://github.com/xuess/info-radar/actions/workflows/ci.yml/badge.svg)
![License](https://img.shields.io/badge/license-MIT-blue.svg)

## 快速开始

```bash
pip install -r requirements.txt
python -m infodigest.cli run          # collect → rate → store → deliver
```

配置：编辑 `config/feeds.yaml`（源注册表）与 `config/rater.yaml`（评分权重/关键词）。

## 架构

```
feeds.yaml → collector(fetch+parse+normalize+dedup) → rater(scorer)
  → storage(SQLite) → formatter(Jinja2) → delivery(飞书/钉钉 webhook)
```

- **无 LLM**：采集、解析、去重、评级、排版、推送全链路确定性代码。
- **无运维**：定时跑在 GitHub Actions，结果推到群机器人。
- **可自托管**：单进程 Python + SQLite，克隆即可跑。

详见 `ARCHITECTURE.md` 与 `docs/`。

## License

MIT
