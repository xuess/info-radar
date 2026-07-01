# RATING_SPEC.md — 规则评级系统 (无 LLM)

## 总分
```
score = 30*authority + 25*freshness + 25*relevance + 10*uniqueness + 10*engagement
```
归一到 0–100。所有子项归一到 0–1 再加权。

## 子项

### 1. authority (源权威, 权重 30)
- 取自 `feeds.yaml` 的 `authority` (0–1)，人工初值。
- 进化循环可按"近 30 天该源被推 A 级条目占比"做微调：`adjusted = 0.7*base + 0.3*recent_ARate`，钳到 [0,1]。

### 2. freshness (新鲜度, 权重 25)
- `Δh` = 发布至今小时数（无发布时间用抓取时间，Δh=0）。
- `freshness = exp(-Δh / 72)`（72 小时半衰期）。
- Δh > 168h(7天) → 直接 0（不参与本轮推送）。

### 3. relevance (关键词相关度, 权重 25)
- `config/rater.yaml` 的 `keywords`：`{word: weight}`。
- 命中位置权重：标题命中 ×1.0，摘要命中 ×0.4。
- `relevance = clamp(sum(hit_weight) / target, 0, 1)`，`target` 为配置（默认=3.0 满分）。
- 无关键词配置时 relevance=0.5（中性）。

### 4. uniqueness (唯一性, 权重 10)
- 与近 7 天已入库条目标题算 Jaccard 相似度 `sim`。
- `uniqueness = 1 - sim`（完全重复→0，全新→1）。

### 5. engagement (热度, 权重 10)
- 若源条目带 `comments`/`points`（如 HN），归一 `min(v / threshold, 1)`（HN threshold=200）。
- 缺省（多数源无）→ 0。不因其缺失扣总分（已体现在权重低）。

## 分级
- `score >= 75` → **A 推荐**
- `50 <= score < 75` → **B 关注**
- `score < 50` → **C 忽略**（默认不推送，除非用户配置 `push_grade_min: C`）

## 配置 (`config/rater.yaml`)
```yaml
weights: { authority: 30, freshness: 25, relevance: 25, uniqueness: 10, engagement: 10 }
freshness_half_life_hours: 72
max_age_hours: 168
relevance_target: 3.0
engagement_threshold: 200
grade_thresholds: { A: 75, B: 50 }
push_grade_min: B
keywords:
  ai: 1.0
  llm: 1.0
  安全: 0.8
  开源: 0.6
  rust: 0.7
  # ...
dedup_similarity: 0.8
dedup_window_days: 7
```

## 可测性要求
- `scorer.score` 纯函数，无副作用，无 IO。
- 测试断言：极旧条目 freshness→0；全命中关键词 relevance=1；与历史完全相同 uniqueness=0；总分在 [0,100]。
- 离线回归 fixture：给定 5 条固定 Entry，断言分数区间与分级稳定（防调参回归）。
