[English](README.md) | [简体中文](README.zh-CN.md)

# OpenGisting

OpenGisting 用 **16 个训练后的 gist 向量**替换客服 agent 的固定规则提示，基座模型不动。Agent 调用工具查询合成订单，再根据验证过的事实回答。

项目同时提供 Full 和 Gist 两种模式，用来核查输入 token 到底省了多少。

[体验在线演示](https://www.myagenthubs.com/opengisting/)。

演示订单均为合成测试数据。查询需要订单号及其演示邮箱。演示页面提供 8 组公开订单示例，仓库中其他演示邮箱已脱敏。种子、canary、运单号、预计送达时间、场景、评测案例、转录及报告均使用合成数据。

![Gisting 输入 token 节省](docs/assets/gisting-savings.png)

## 怎么对比 Full 和 Gist

固定规则段从 **526 个输入 token 缩减至 19 个**，其中包括 16 个 gist 位置及 3 个系统框架 token。工具 schema、对话历史和工具结果不在压缩范围内。

网页用 **968 → 461 个输入 token** 示意每次调用的节省，减少约 52.4%。计算方式是：固定规则 + 395 个工具 token + 四舍五入后的 47 个历史及结果 token。

这个示意固定了上下文长度：两边都使用 Gist 调用的平均历史及结果长度。它方便看出规则压缩的作用，但不能当作两个模式各自的实际输入均值。

报告各评测 933 个案例，其中各有 877 个使用模型的回合。每个此类回合的实际平均输入为 Full 的 971.184 和 Gist 的 477.734，模型调用分别为 881 次和 908 次。

这些数字衡量输入 token 的节省。运行延迟和答复质量需要单独验证；报告分别统计模型原始输出和运行时检查后的最终回复是否出错。

证据：[Full 报告](eval/reports/ee6c5c626278120523b9af02255958c0c9f5048c/full/report.json)、[Gist 报告](eval/reports/ee6c5c626278120523b9af02255958c0c9f5048c/gist/report.json)、[构成计算代码](src/gisting/eval/web_benchmarks.py)。仅训练 16 个 gist 向量，Qwen3-1.7B 权重保持不变。

[Gist 权重及 manifest](https://huggingface.co/ImPanda/how-shopify-gisting-works) 已发布到 Hugging Face。下载命令及精确兼容性要求见[使用指南](docs/guides/using-gist-tokens.zh-CN.md)。

## 阅读指南

[中文指南索引](docs/guides/INDEX.zh-CN.md)

- [架构](docs/guides/architecture.zh-CN.md)：模型决策、工具和最终回复。
- [使用 gist tokens](docs/guides/using-gist-tokens.zh-CN.md)：需要哪些 Gist 文件，以及如何选择运行模式。
- [固定规则](docs/guides/fixed-rules.zh-CN.md)：526 → 19 究竟替换什么。
- [训练](docs/guides/training.zh-CN.md)：只训练 gist 向量，怎样检查训练和比较结果。

## 仓库结构

- `src/gisting/`：提示构建、工具、agent、模型服务、训练和评测。
- `apps/web/`：聊天界面及输入 token 说明。
- `apps/gateway/`：请求验证、配额和服务代理。
- `prompts/`、`kb/`、`data/`：规则、知识及合成数据。
- `eval/`：案例、评分器、指标、基线和记录报告。
- `contracts/`：与网页共享的生成 schema。
- `scripts/`、`tests/`：检查及离线测试。
- `docs/design/`、`docs/decisions/`：设计及工程决策。

## 快速开始

使用 Python 3.11、uv、Node.js 和 pnpm。gitleaks、shellcheck 等可选工具扩展检查范围。

```sh
uv sync
make check
make check-ts
```

这些命令安装依赖并运行检查，不下载模型权重或启动服务。模型配置见 [下载脚本](scripts/download-models.sh) 和 [使用指南](docs/guides/using-gist-tokens.zh-CN.md)。环境变量名称和留空的密钥占位可在 `.env.example` 中查看。

## 许可与致谢

OpenGisting 使用 [Apache-2.0](LICENSE) 许可。基座模型 [Qwen3-1.7B](https://huggingface.co/Qwen/Qwen3-1.7B) 也采用 Apache-2.0 许可。

本项目学习自 Shopify Engineering 的 [Gisting 文章](https://shopify.engineering/gisting)。
