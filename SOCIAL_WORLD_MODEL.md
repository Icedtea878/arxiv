# Social World Model 配置

每日从 8 个 arXiv 分类读取最新公告：cs.AI（人工智能）、cs.CL（自然语言处理）、cs.LG（机器学习）、cs.MA（多智能体）、cs.HC（人机交互）、cs.SI（社会与信息网络）、cs.CY（计算机与社会）、cs.CV（计算机视觉）。分类含义见 https://arxiv.org/category_taxonomy 。

仓库 Settings → Secrets and variables → Actions → Variables：

| 变量 | 默认值 | 含义 |
| --- | --- | --- |
| CATEGORIES | cs.AI,cs.CL,cs.LG,cs.MA,cs.HC,cs.SI,cs.CY,cs.CV | 公告分类 |
| MAX_PAPERS_PER_CATEGORY | 100 | 每个分类最多获取的候选论文数 |
| MAX_PAPERS_PER_DAY | 200 | 去重、排序后每天最多进行 AI 摘要的篇数 |

候选论文先跨分类去重，与过去七天已收录记录去重，再按标题和摘要的主题关键词排序。Social world model、social simulation、theory of mind、mental state 等词优先；关键词表在 `daily_arxiv/select_papers.py`。这只是启发式排序，不保证相关性，也不会硬性排除无关键词论文。没有命中关键词的论文会在额度剩余时补入。

上限不是每天的固定篇数，也不代表全站或历史论文的数量。繁忙分类超出候选上限的论文可能未覆盖。增加上限会增加 MiniMax 费用与运行时间。arXiv 抓取串行执行，元数据批量获取，每次至少间隔五秒；AI 同样串行处理。工作流不并发执行。最新公告不等于按日历日期筛选的所有论文。

首页“数据集”进入 `datasets.html`：按 Hugging Face 仓库名称查找公开数据集，提供数据卡、许可、下载量和仓库标注的 arXiv 论文链接。未标注论文时提供同名论文检索入口，不保证搜出的论文就是原始数据集论文。Google Dataset Search 与 arXiv 是外部检索入口。此功能不消耗 MiniMax 配额，也不下载数据集。单次最多 30 条结果，10 分钟内重复搜索使用缓存；遇到 HTTP 429 暂停一分钟。
