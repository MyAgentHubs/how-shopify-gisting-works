---
type: guide
status: current
updated: 2026-10-07
summary: 准备兼容的 Gist 文件，按 ID 插入向量，并核查 Full 与 Gist 的比较。
---

# 使用 gist tokens

[English](using-gist-tokens.md) | [简体中文](using-gist-tokens.zh-CN.md)

这个项目使用 **Qwen3-1.7B**，记录的版本为 `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`，隐藏维度为 **2048**。参见[候选模型](../../models/candidates.json)。

训练得到的张量是 `gist.safetensors` 中的 `gist`：float32，形状为 **16 × 2048**，即 32,768 个学习得到的标量值。只训练这些 gist 向量，基座模型权重不动。

**Gist 权重即将发布到 Hugging Face。** 本指南不提供可下载的 Gist 文件。运行 Gist 需要自行准备兼容的已训练 gist 向量和 manifest。

## 前置条件

使用 Python 3.11 和 uv。基础检查需要默认依赖；模型运行和训练还需要 `model` 扩展依赖（torch、transformers、safetensors）。参见[依赖声明](../../pyproject.toml)。

从仓库根目录运行命令。下面的设置命令由你按需执行，会下载基座权重；gist 权重需要另行准备。下载脚本还需要 `huggingface_hub`（版本 0.34 或更新）提供的 `hf` CLI、Bash 及其校验和工具。

```sh
uv sync --extra model
export GISTING_MODELS_DIR=./models/hf
bash scripts/download-models.sh qwen3-1.7b
export GISTING_MODEL_DIR=./models/hf/qwen3-1.7b
```

加载器只使用本地文件。将 tokenizer 文件、配置、基座权重、`.revision` 和 `SHA256SUMS` 一同保存在该模型目录。可用 `GISTING_DEVICE` 选择 torch 设备；省略时使用加载器的默认设置。

Gist 文件必须匹配运行时的 backend ID，包括 dtype。更改设备／backend 后，现有文件可能无法使用，需要准备新匹配的文件，并保留 manifest 检查。

## 按 ID 把 gist token 插进 prompt

[`gist_rules()`](../../src/gisting/prompt/assemble.py) 将**同一个**占位 ID 重复 16 次。该 ID 比 tokenizer 的最大词表 ID 大一，但仍须位于模型的 embedding 表范围内。这会留出 16 个位置，不会添加 16 个新的可见词表字符串。

在输入 embedding 阶段，[`embed_with_gist()`](../../src/gisting/model_server/gist.py) 按顺序在这些位置替换为 16 行学习得到的向量。它不会改变基座 embedding 权重。在聊天中输入所谓的 gist token，不会激活这条路径。

[Gist 文件加载器](../../src/gisting/model_server/gist_store.py)验证 manifest 字段、gist 校验和、float32 形状及占位容量。兼容性检查包括基座版本及校验和列表哈希、展开规则哈希、工具 ID 哈希、隐藏维度、占位 ID 和 backend ID。

Manifest 还记录数据集及训练配置哈希；`training compare` 会将这些哈希与提供的教师文件／配置进行核对。

[用户文本 token 化](../../src/gisting/prompt/tokenizer.py)拆分 added-token 的文本拼写，使其无法转化为控制 ID。用户、工具和 KB 内容始终是不可信文本；只有提示组装会插入可信的控制 ID 和 gist ID。这在客户输入角色／工具标记时保持了安全边界。

## 运行前的离线检查

这些命令读取已提交的数据或显示解析器帮助；不会生成模型输出、运行评测或训练：

```sh
uv run python scripts/check_benchmarks_data.py
uv run python scripts/check_docs.py
uv run python -m gisting.agent --help
uv run python -m gisting.agent run --help
uv run python -m gisting.training --help
```

[Full 报告](../../eval/reports/ee6c5c626278120523b9af02255958c0c9f5048c/full/report.json)和 [Gist 报告](../../eval/reports/ee6c5c626278120523b9af02255958c0c9f5048c/gist/report.json)记录了 933 个案例的比较。请检查 `tokens`、`cases`、`run` 及原始／最终指标层。[网页构成推导](../../src/gisting/eval/web_benchmarks.py)解释了受控的 968 → 461 示意。四舍五入和分母详见[固定规则](fixed-rules.zh-CN.md)。

## 按需运行 Full 和 Gist

以下命令确实会加载模型并生成回复。它们使用本地合成数据传输，而非真实 Shopify API。必须存在 `data/demo-orders/` 下的本地样例。

设置仅供演示使用的邮箱密钥，并显式提供空的项目相对路径 env 文件，避免使用默认凭据文件。在 Bash 中，通过下方静默的 `read` 提示输入一个新的、仅供演示使用的密钥。示例在没有凭据的情况下询问配送，因此无需真实订单邮箱。运行时仍会构建工具依赖。

```sh
mkdir -p artifacts
: > artifacts/local-runtime.env
read -r -s GISTING_EMAIL_SECRET
export GISTING_EMAIL_SECRET
printf '%s\n' '{"session_id":"local-full","messages":[{"role":"user","content":"Where is my order?"}]}' |
  uv run python -m gisting.agent run --mode full --transport local --env-file artifacts/local-runtime.env
```

运行 Gist 时，将下方路径替换为你的兼容 Gist 文件目录，其中须包含 `manifest.json` 和 `gist.safetensors`：

```sh
export GISTING_GIST_DIR=./artifacts/gist/example-run
printf '%s\n' '{"session_id":"local-gist","messages":[{"role":"user","content":"Where is my order?"}]}' |
  uv run python -m gisting.agent run --mode gist --transport local --env-file artifacts/local-runtime.env
```

两种模式都从 stdin 接收一个 JSON 请求，并在 stdout 输出 `answer` 和公开 `trace`。`--internal` 添加内部追踪记录，供本地检查；`--batch` 接收 stdin 每行一个请求。

代码返回带类型、有明确名称的回退结果时，会记录具体原因，并返回退出码 1；用法／加载错误返回退出码 2。默认工具传输为 HTTP，因此这些示例须保留 `--transport local`。各次 CLI 调用是独立进程；需要持久会话和共享失败限制时使用 serve。

[架构](architecture.zh-CN.md) | [训练自己的 gist 向量](training.zh-CN.md)
