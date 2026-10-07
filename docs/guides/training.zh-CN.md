---
type: guide
status: current
updated: 2026-10-07
summary: 用记录的教师响应训练 gist 向量，检查基座权重不变，并说明比较范围。
---

# 训练 gist 向量

[English](training.md) | [简体中文](training.zh-CN.md)

Full 教师和 Gist 学生使用**同一个冻结的 Qwen3-1.7B 模型**。教师读取展开的规则，学生在同一段读取 16 个学习得到的输入向量。两者都保留工具 schema 和对话上下文。

训练让学生在较短的规则输入下学习教师的预测分布，这个目标称为上下文蒸馏。只训练 gist embedding，基座权重不动；训练不会得到一个更小的替代模型。

## 训练怎么计算损失

[`run_training()`](../../src/gisting/training/gist_run.py) 禁用全部网络参数的梯度，并在训练前后计算这些参数的哈希。哈希变化会触发错误。[`AdamW`](../../src/gisting/training/trainer.py) 只接收 `[run.gist]`，权重衰减为零；梯度裁剪也仅针对 gist。

对于每条保留的教师记录，教师和学生都接收**同一组记录的响应 ID**，作为继续预测的输入。每一步都使用记录中的响应，而不是各自新生成的响应，这种做法叫 teacher forcing。

教师在不计算梯度的情况下重新计算下一个 token 的分布，学生用注入的 gist embedding 计算对应分布。[`kl_per_token()`](../../src/gisting/training/forward.py) 在完整词表上计算 `KL(P_teacher || P_student)`，随后训练在选定的响应位置之间、以及 batch 内的样例之间取平均。

[`make_example()`](../../src/gisting/training/examples.py) 选择从 `prefix_length - 1` 到 `prefix_length + target_length - 2` 的下一个 token 预测位置，并为每个前缀分别设置偏移。它覆盖**每一个记录的响应 token**，包括措辞及工具调用语法／参数。当生成以 `stop` 结束时，[`target_ids()`](../../src/gisting/training/teacher.py) 会附加消息结束 ID，因此也会训练停止预测。前缀位置不是损失目标。当 Full 前缀 + 目标长度超过配置的最大值时，会跳过过长样例。

选择什么标准筛选样本，与哪些 token 参与损失计算，是两件独立的事。`filter` CLI 默认使用 `decision`（行动和事实），而底层过滤函数默认使用 `raw`。`read_teacher()` 默认在 `raw` 层重新评分，但样例构建不会使用该判定来丢弃记录或屏蔽 token 位置。

按 decision 标准过滤，只决定保留哪些样本。保留样本中的全部响应 token 和正常结束预测仍参与 KL 计算。实现中没有只选择决策／事实 token 的语义掩码。

## 准备数据，再检查保留和拒绝的样本

[`build_dataset()`](../../src/gisting/training/dataset.py) 根据带种子的模板和类别抽取合成样本，按模板家族划分数据集，并使用来自 [`data/gist/`](../../data/gist/templates.json) 和合成计划的订单池。相同设置可以复现这些样本。样本包含首次调用决策及多回合／工具结果上下文。

`teach` 记录 Full 模式的响应 ID／文本、结束原因、token 数、耗时、backend 身份及评分器判定。记录可按样本 ID 续写；新教师／配置应使用新的输出文件，避免混合运行。

`filter` 确定性地重新评分记录，保留通过的记录，并报告各划分／类别的总数、拒绝数及空组。复现实验时应显式选择评分层。

接受训练数据之前，应人工检查跨类别和数据划分的部分保留及拒绝记录。检查行动参数、有依据的事实、拒绝、缺失输入及同意；记录抽样选择和发现。

这一步需要人工审查，**这些 CLI 没有实现对应的自动门禁**。空组报告本身也不会阻止训练。KL 降低只能说明这个训练目标上的变化，不能证明运行时正确，也不能证明发布评测通过。

## 按顺序运行训练

下面的命令会实际生成教师响应，再训练 gist 向量，需要训练时再执行。首先遵循[使用前置条件](using-gist-tokens.zh-CN.md)：Python 3.11、`uv sync --extra model`、带 tokenizer 及校验和元数据的固定版本本地基座模型，以及指向其目录的 `GISTING_MODEL_DIR`。`GISTING_DEVICE` 为可选项。

这些训练命令使用构造的合成样本及记录的上下文；不会调用真实 Shopify API，也不需要真实演示凭据。

```sh
mkdir -p artifacts/tutorial
uv run python -m gisting.training build --out artifacts/tutorial/dataset.jsonl
uv run python -m gisting.training teach --dataset artifacts/tutorial/dataset.jsonl --out artifacts/tutorial/teacher.jsonl
uv run python -m gisting.training filter --teacher artifacts/tutorial/teacher.jsonl --layer decision --out artifacts/tutorial/train_set.jsonl
uv run python -m gisting.training gist --teacher artifacts/tutorial/train_set.jsonl --run-id example-run --out-dir artifacts/gist
uv run python -m gisting.training compare --teacher artifacts/tutorial/train_set.jsonl --gist-dir artifacts/gist/example-run --out artifacts/tutorial/compare.json
```

省略 `--out` 时，`build` 写入 stdout。省略 `--dataset` 时，`teach` 读取 stdin，并支持 `--limit`；`--out` 为必需项，支持通过追加记录续写。`filter` 支持 `decision`、`raw` 和 `final`。小规模 `--limit` 试跑，或过滤后为空／不均衡的数据分区，都不足以构成有意义的训练运行。

[`data/gist/hparams.json`](../../data/gist/hparams.json) 设置 k = 16、seed = 20261002、学习率 = 0.005、epochs = 6、batch size = 4、最大长度 = 2560、梯度裁剪 = 1.0、分块均值初始化及梯度检查点。分块均值初始化从 Full 规则的 embedding 分块中派生向量；实现也支持随机初始化。配置位于数据文件中，而非额外的未记录 CLI 参数。

## 训练输出是什么，比较覆盖哪些样本

`gist` 写入 `artifacts/gist/<run-id>/gist.safetensors`、`manifest.json`、`training-log.jsonl` 和 `summary.json`。目录中已有 `gist.safetensors`、`manifest.json` 或 `summary.json` 中的任一文件时，会拒绝写入，需要选择新的 run ID。

此配置的 float32 `gist` 张量为 16 × 2048。[Manifest](../../src/gisting/training/artifact.py) 绑定基座版本／校验和元数据、规则／工具哈希、维度、占位 ID、backend、教师文件哈希、超参数哈希及 gist 校验和。

摘要记录训练前后的基座参数哈希及权重未改变的状态，还记录数据集计数、被跳过的过长样例 ID，以及 KL 进展。

`compare` 核对训练数据和配置等记录是否匹配，仅在所提供教师数据集的 **dev 分区**上运行 Full、未训练 Gist 和已训练 Gist，并按 `decision` 标准评分。它写入比较报告及样本输出。

README 链接的独立完整 agent 评测包含 933 个 train／dev 案例，不能与这里的比较混用。这里的 `compare` 不会覆盖完整的 serve／gateway／运行时路径。`artifacts/` 下的训练来源示例文件不作为公开证据导出。需要时使用 `build` 和 `teach` 重新创建。

规则或工具变化后，需要在新周期中生成匹配的 Gist 文件并进行评测。复现已有结果时，保持冻结的提示、案例和基线完整不变。

[固定规则边界](fixed-rules.zh-CN.md) | [架构](architecture.zh-CN.md)
