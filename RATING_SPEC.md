# RATING_SPEC.md — 规则评级系统 (无 LLM)

## 总分公式（策展版）

```
base   = 30*authority + 25*freshness + 25*relevance + 10*uniqueness + 10*engagement
final  = clamp(base * interest_weight + event_boost - decay + novelty, 0, 100)
```

- `base`：五维客观分（0–100）
- `interest_weight`：来自 `config/user_interests.yaml`（按 category/tags 取最高匹配，默认 1.0）
- `event_boost`：`event_patterns` 命中 S/A/B 档位加成
- `decay` / `novelty`：来自事件历史（重复故事衰减；新进展关键词加分）

归一到 0–100。所有子项归一到 0–1 再加权。

## 子项

### 1. authority (源权威, 权重 30)
- 取自 `feeds.yaml` 的 `authority` (0–1)，人工初值。
- 进化循环可按"近 30 天该源被推 S/A 级条目占比"做微调：`adjusted = 0.7*base + 0.3*recent_highRate`，钳到 [0,1]。

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

### 6. event_tier（事件档位加成）
- `event_patterns.S/A/B.keywords` 子串匹配（短 ASCII 词用词边界，避免 RCE⊂source）。
- 命中即加 `boost`（默认 S=20 / A=12 / B=5），取最高档。

### 7. interest_weight（兴趣权重）
- 匹配 `user_interests.yaml` 中 category 与 tags，取最大值。
- 无匹配 → `default_weight`（默认 1.0）。

### 8. decay / novelty（时序）
- 历史见过：每天按档位衰减（S:20 / A:15 / B:10），7天内出现≥3次额外 -10。
- 标题/摘要含 novelty 关键词（发布/首次/…）→ +novelty_bonus。

## 分级
- `score >= 90` → **S 必看**
- `score >= 75` → **A 推荐**
- `50 <= score < 75` → **B 关注**
- `score < 50` → **C 忽略**（不推送）

## 策展层（推送前）

对齐 openclaw「宁可少说，不可凑数」：

1. 噪声标题过滤（`noise_patterns`）
2. S/A 必须有有效 http(s) 链接
3. 事件历史：48h 内不重复；≥5 次强制归档；≥3 次降级展示
4. 日配额：S≤3 / A≤8 / B≤12（可配）
5. 无达标条目 → **静默不推**（`allow_empty_digest: true`）

## 配置 (`config/rater.yaml` + `user_interests.yaml`)
```yaml
weights: { authority: 30, freshness: 25, relevance: 25, uniqueness: 10, engagement: 10 }
grade_thresholds: { S: 90, A: 75, B: 50 }
dedup_similarity: 0.75          # SequenceMatcher + Jaccard 取 max
dedup_hours: 48
daily_quotas: { S: 3, A: 8, B: 12 }
min_push_score: 50
allow_empty_digest: true
```

## 可测性要求
- `scorer.score` 纯函数（decay/novelty 经 ScoreContext 注入），无副作用，无 IO。
- `EventHistory` / `curate` 有独立单测：48h、降级、归档、配额、静默。
- 离线回归 fixture：给定 5 条固定 Entry，断言分数区间与分级稳定（防调参回归）。
