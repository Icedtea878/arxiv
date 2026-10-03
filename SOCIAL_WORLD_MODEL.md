# Social World Model 配置

每日北京时间 01:30（UTC 17:30）触发 GitHub Actions；实际开始时间可能延迟。也可在 Actions → arXiv-daily-ai-enhanced → Run workflow 手动运行。

当前流程：抓取最多 800 篇候选 → 跨分类及七日历史去重 → 按关键词和数据集组合规则排序，取最多 200 篇 → MiniMax 只阅读标题和原始英文摘要，逐篇评估相关性 → 严格大于 80 分的论文发布到网页。不凑满 200 篇；80 分不保留，全部未达标则发布空结果。筛选后仍按关键词排名展示，网页关键词可继续匹配、高亮和置顶。

LLM 范围包含个体建模/模拟、个体交互、群体模拟、社会模拟，任意方向直接相关即可，不要求必须研究心理状态转移。完整评分标准在 ai/relevance_prompt.txt：91–100 核心直接相关、81–90 清楚相关且可借鉴、61–80 邻近但直接用途或证据不足、31–60 弱相关、0–30 无关。分数是模型判断，不是经过校准的概率；只依据摘要，可能误判，也不能核实全文中的数据集属性。输出 score、directions 和一句中文 reason。

工作流暂不生成长总结，也不让 LLM 阅读全文。评分会消耗 MiniMax 输入/输出 token；串行请求并缓存成功结果。短理由不保证推理模型的总 token 消耗一定很低，实际费用以 MiniMax 账单为准。缓存按标题、摘要、模型、接口、评分提示词计算；仅改变阈值或关键词排名可以复用评分。GitHub 可能清理缓存。

API/格式失败不记作零分：保存成功检查点及失败报告，停止当次发布，重跑复用成功结果。有效评分全部低于阈值与请求失败是两种不同状态。旧日期未评分论文保留浏览入口并明确标注“历史论文：尚未进行 LLM 相关性评分”；新数据优先加载日期_relevance.jsonl。

仓库 Settings → Secrets and variables → Actions → Variables：

| 变量 | 默认值 | 含义 |
| --- | --- | --- |
| CATEGORIES | cs.AI,cs.CL,cs.LG,cs.MA,cs.HC,cs.SI,cs.CY,cs.CV | 8 个公告分类 |
| MAX_PAPERS_PER_CATEGORY | 100 | 每类最多抓取篇数 |
| MAX_PAPERS_PER_DAY | 200 | 关键词预选及 LLM 评分篇数上限 |
| RELEVANCE_THRESHOLD | 80 | 仅保留严格大于此分数的论文 |
| RESEARCH_PROFILE | research_profile.json 对应 JSON | 关键词、权重、组合及追踪词；变量优先于文件 |
| MODEL_NAME | MiniMax-M2.7 | 评分模型 |

Secrets 使用现有 OPENAI_API_KEY（MiniMax 中国站）和 OPENAI_BASE_URL；不需要 Jev。网页 Settings 关键词只影响本地匹配，不改变后台 RESEARCH_PROFILE 或 LLM 标准。

关键词标题命中默认乘 2；同词重复不累加。已覆盖 individual/user/human modeling、interpersonal interaction、group/crowd/population simulation、collective behavior、opinion dynamics、social influence、societal simulation 等四个方向，以及原有人格、心理状态、行为预测关键词。预选仍可能漏掉没有这些词的相关论文。

数据集规则仍为三档组合取最高值：数据发布词 + 人格/模拟词 +6；数据发布词 + 个体/历史词 + 行为/预测词 +7；数据发布词 + 纵向观测词 + 人格/状态词 +8。通用发布词合计最多 +1，有效追踪名称合计 +4，领域/有效名称标题命中再 +2。兼容大小写、空格、连字符、E²/E2；OPeRA 和 REALTALK 需要摘要领域背景及发布词。方法榜、数据集榜只是通过筛选论文的标签视图，不是额外名额，不代表已核实数据集属性。

结果入口：https://icedtea878.github.io/arxiv/ 。Actions 运行 Summary 显示评估数、保留数和缓存数。Artifacts 中 research-rankings 保存预选排名和候选；ai-progress 保存评分报告和检查点（14 天）。data 分支日期_relevance_report.json 包含每篇分数、理由和运行 token 统计（仅已成功解析响应的供应商 usage，不是完整账单）。日期_relevance.jsonl 只包含保留论文；日期_rankings.* 是筛选前的关键词排名。

最多 800 篇是上限，跨分类重叠、历史去重和公告数量会使实际更少。arXiv 抓取串行，元数据请求间隔至少五秒；工作流不并发。最新公告不等于该日历日发布的所有论文。

独立“数据集”页面仍查找 Hugging Face 公开数据集，并提供数据卡、许可、论文链接等；不消耗 MiniMax token，不下载数据集。论文里的数据集标签与此搜索入口独立。
