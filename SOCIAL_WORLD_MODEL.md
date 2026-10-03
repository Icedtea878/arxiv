# Social World Model 配置

每日从 8 个 arXiv 分类读取最新公告：cs.AI（人工智能）、cs.CL（自然语言处理）、cs.LG（机器学习）、cs.MA（多智能体）、cs.HC（人机交互）、cs.SI（社会与信息网络）、cs.CY（计算机与社会）、cs.CV（计算机视觉）。分类含义见 https://arxiv.org/category_taxonomy 。

仓库 Settings → Secrets and variables → Actions → Variables：

| 变量 | 默认值 | 含义 |
| --- | --- | --- |
| CATEGORIES | cs.AI,cs.CL,cs.LG,cs.MA,cs.HC,cs.SI,cs.CY,cs.CV | 公告分类 |
| MAX_PAPERS_PER_CATEGORY | 100 | 每个分类最多获取的候选论文数 |
| MAX_PAPERS_PER_DAY | 200 | 从全部候选统一排序后收录的上限，也是 AI 摘要上限 |
| RESEARCH_PROFILE | 与 research_profile.json 相同的 JSON | 关键词、权重、分组、组合规则及数据集名称追踪 |

候选论文先跨分类去重，与过去七天已收录记录去重。每类候选最多 100 篇，8 类最多 800 篇；分类间重叠或历史去重会减少候选。全部候选按“方法关键词得分 + 数据集规则得分”的总分从高到低统一排序，取前 200 篇生成 AI 摘要并展示。不设置每种论文的独立名额；不足 200 篇就展示实际数量，相关论文少时会包含低分或零分论文。纯关键词规则计算不调用 AI，不消耗模型 token。

方法关键词得分：标题、英文摘要匹配 method_keywords 后累加得分，同一个词不因重复出现而加分；标题命中乘 title_multiplier（默认 2）。human simulation、user simulation、persona graph、mental state transition、individual behavior prediction 等用户研究词已经加入。method_min_score=4 仅决定是否打上方法论文标签，不决定是否进入总排名前 200。

数据集榜：数据发布词与领域词组合匹配，三档组合分 +6/+7/+8 只取最高一档。所有通用数据发布词合计最多额外 +1；dataset/benchmark 单独出现不入榜。有效追踪名称合计 +4，不按名称个数累加；研究领域词或有效名称出现在标题再加 +2，通用数据发布词不享受此标题加分。名称匹配不区分大小写，兼容空格、连字符、E²/E2。OPeRA、REALTALK 需要同时出现数据发布词，且英文摘要包含领域背景词才计入名称追踪。这仍是文本规则，不是 AI 语义判定，也不能仅凭标题摘要确认论文发布了新数据集。

**修改关键词的位置**：GitHub Settings → Secrets and variables → Actions → Variables → RESEARCH_PROFILE。这里保存完整 JSON；method_keywords 是方法词权重，groups 是数据类型词组，combination_rules 是组合规则，dataset_names 是名称追踪表。变量未设置时，脚本回退使用仓库 research_profile.json。文件和变量的值是两份配置，设置变量后以变量为准。JSON 不合法会明确报错，避免静默使用错误配置。网页 Settings 里的个人关键词只控制浏览器匹配与高亮，不会写入此变量。

同分按 arXiv ID 排序。网页默认显示全部前 200 篇，卡片显示研究总排名、总分；方法论文/数据集论文选项只是进一步查看前 200 篇内相应标签的论文，不占独立名额。鼠标悬停得分可查看命中关键词与组合规则。你可以再添加网页关键词，在这 200 篇中匹配、高亮并把命中项置顶；不会改变卡片标注的后台排名。网页匹配现在包含英文原始摘要。

每天生成 data/日期_rankings.json 和 data/日期_rankings.md，保存总排名、标签榜单、命中词、组合分与核验提示；候选保存 data/日期_candidates.jsonl。Actions 运行详情的 Summary 可直接看排名，Artifacts 可下载报告和候选。选中论文的 AI 摘要成功后，报告也提交到 data 分支；没有新候选时跳过付费摘要。数据集四项人工核验（真人、稳定个体 ID、时间信息、可留出的行为标签）全部初始标注“待人工核验”，只附摘要中的文字提示，不宣称已核实。

上限不是每天的固定篇数，也不代表全站或历史论文的数量。繁忙分类超出候选上限的论文可能未覆盖。增加上限会增加 MiniMax 费用与运行时间。arXiv 抓取串行执行，元数据批量获取，每次至少间隔五秒；AI 同样串行处理。工作流不并发执行。最新公告不等于按日历日期筛选的所有论文。

首页“数据集”进入 `datasets.html`：按 Hugging Face 仓库名称查找公开数据集，提供数据卡、许可、下载量和仓库标注的 arXiv 论文链接。搜索心智理论时使用 `theory-of-mind`；缩写 `ToM` 太短，会匹配到无关仓库。未标注论文时提供同名论文检索入口，不保证搜出的论文就是原始数据集论文。Google Dataset Search 与 arXiv 是外部检索入口。此功能不消耗 MiniMax 配额，也不下载数据集。单次最多 30 条结果，10 分钟内重复搜索使用缓存；遇到 HTTP 429 暂停一分钟。
