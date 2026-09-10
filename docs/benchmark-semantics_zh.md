# AgentX 行为与黄金接受契约

<div align="center">

[English](./benchmark-semantics.md) | **中文**

</div>

InferenceX 将 AgentX 请求行为与黄金接受长度策略暴露为带版本、严格校验的数据。消费者应加载这些文档，不再从启动器文本、文件名、注释或 GitHub Actions 日志中反向推断语义。

Wire format 的权威定义是 [`schemas/inferencex-benchmark-semantics-v1.json`](../schemas/inferencex-benchmark-semantics-v1.json)。严格加载器与跨字段校验器位于 [`infx/semantics`](../infx/semantics)，支持的命令行入口是 [`utils/benchmark_semantics.py`](../utils/benchmark_semantics.py)。两类文档都会拒绝未知字段。

## 文档类型与稳定性

| `document_type` | Payload | 用途 |
| --- | --- | --- |
| `inferencex.behavior-contract` | `behavior` | 有效的 AgentX benchmark、请求、trace、路由、token 计数和逐角色推测解码方案 |
| `inferencex.golden-acceptance-curve` | `curve` | 经审阅且带完整溯源信息的黄金接受长度单元集合 |

两者都是 v1 契约。消费者可以依赖 v1 中已命名字段与枚举值，但必须拒绝不支持的 `schema_version`。可空字段或 `unknown` 表示该事实尚未确定，而不是选择某个隐式默认值。

每份文档都包含 `generated_at`。行为契约包含 `contract_id` 与 `contract_digest`，曲线包含 `curve_id` 与 `curve_digest`。Digest 使用 RFC 8785 JSON 规范化和 SHA-256。`curve_digest` 覆盖除自身外的完整 `curve`；`contract_digest` 覆盖计划行为，但排除 `contract_id`、`contract_digest` 和 `runtime_verification`。固定的 `contract_digest_scope` 字段记录这一投影规则，因此可以追加运行时观测，而不改变被验证方案的身份。

## 行为契约

`resolved` 行为契约是判断两个 AgentX 结果在行为上是否可比所需的完整运行前描述。必需部分包括：

- `benchmark_protocol`：profile 与 benchmark ID、canonical/fast/diagnostic 模式、精确的客户端实现、时长、warmup、trace 语料库和 revision、时序与 cache-bust 行为、失败策略及有效性规则。
- `request`：API 与 endpoint、streaming、服务模型字段、完整 `extra_body`、已解析的思考状态及客户端/服务端编码、chat template 身份与 kwargs、采样参数、headers、会话亲和性、tool choice、响应解析和 tokenizer 身份/计数规则。
- `speculative_decoding`：声明的方法，以及 `aggregated`、`prefill` 或 `decode` 的唯一有效角色条目。每个角色记录草稿身份、接受模式、全部具体注入，以及可用时的有效服务配置 digest。
- `source`：用于解析行为的 InferenceX commit 和不可变源码指针，以及显式 warning。

当 `status=resolved` 时，思考状态不能是 `unknown`，chat template 身份必须已解析，推测角色也必须一致。校验器还检查普通 JSON Schema 不便表达的关系：所选曲线的方法与草稿长度必须匹配所属角色，曲线思考状态必须匹配请求思考状态，注入角色必须匹配容器角色，接受长度必须位于 `[1, K + 1]`。

`status=partial` 是明确、诚实的兼容性收据。它有 digest，但可空部分与 `extensions.missing_fields` 会显示哪些事实无法确定。Partial 契约可用于诊断和历史结果入库，但不能证明两个运行使用了相同行为。

### 思考模式与 chat template

思考模式由已解析状态以及独立的客户端/服务端编码共同表示。这样不会把 `thinking=true`、`enable_thinking=false` 或引擎默认值压缩成一个猜测的布尔值。能够识别的编码如相互矛盾，校验会失败。

已解析的 chat-template 契约会说明是否使用模板、tokenization 在哪一侧执行、选择哪个 tokenizer 默认/file/inline 模板、适用时的内容 digest、两侧 kwargs 以及 `add_generation_prompt`。已解析契约不能使用 `template.kind=unknown`。

### 合成接受与真实接受

`synthetic_golden` 必须选择一个精确曲线单元，并至少包含一个仅用于吞吐量的注入。为准确率物化时，会移除合成曲线选择，并将具体恢复操作记录为 `mode=real`、`evaluation_scope=accuracy`。`disabled` 不允许曲线或注入。

Helper 会生成以下标准 framework 转换：

| Framework | Surface | 编码 |
| --- | --- | --- |
| vLLM | `/speculative_config/rejection_sample_method` 与 `/speculative_config/synthetic_acceptance_length` | 选择 synthetic rejection，并原样传递 AL |
| SGLang | `SGLANG_SIMULATE_ACC_LEN`、`SGLANG_SIMULATE_ACC_METHOD`、`SGLANG_SIMULATE_ACC_TOKEN_MODE` | 原样传递 AL，并设置 `match-expected` 与 `real-draft-token` |
| TensorRT-LLM | `TLLM_SPEC_DECODE_FORCE_NUM_ACCEPTED_TOKENS` | 传递 `AL - 1`，因为该变量不包含验证 token |
| ATOM | `--spec-decode-acceptance-length` | 原样传递 AL |

每项注入都包含其拓扑角色、framework、surface、精确位置、转换、编码后的值、测量范围和原生值。原生值使移除/恢复操作显式化，无需假设引擎默认值。

## 黄金接受曲线

曲线选择采用精确匹配。调用方必须提供 `curve_id`、`model_key`、思考状态、推测方法、variant 与 `num_speculative_tokens`；resolver 不会规范化别名，也不会从文件名推断身份。零个或多个匹配都会失败。Draft 曲线必须显式使用 `--allow-draft`；正常的可比运行只能解析 `active` 曲线。

每条曲线记录：

- 稳定的模型、目标 checkpoint、草稿 checkpoint/head 类型、method 与 variant 身份；
- 独立的思考模式，以及每种模式准确的采样与 chat-template 行为；
- 每个草稿长度唯一的点，包括平均 AL 与显式分布表示；
- dataset、split、不可变 revision/digest、category、prompt 数、输出长度、公式、统计量、舍入、framework/image/hardware、collector 源码、workflow run 和保留的 artifact；
- 审阅状态、审阅者、审阅时间与备注。

`kind=mean_only` 的分布不会虚构概率。PMF 必须包含 `K + 1` 个且总和为一的概率；逐位置概率表必须包含 `K` 个非递增概率。派生分布与经验分布必须说明 derivation。

`active` 曲线必须已获批准，并具有完整、不可变的目标模型、dataset、framework、image、artifact 和审阅溯源信息。外部草稿 checkpoint 同样必须不可变。[`golden_al_distribution/v1`](../golden_al_distribution/v1) 中的 v1 companion 保留了旧 YAML 的每个数值单元，但仍为 `draft`/`pending`，因为不能虚构缺失的历史 revision 与 artifact digest。在曲线完成审阅并激活前，旧 YAML 仍是当前运行时权威。

## 命令

使用明确的轻量依赖运行 CLI：

```bash
SEMANTICS_RUN=(uv run --no-project --python 3.12 \
  --with 'pydantic>=2' --with 'PyYAML>=6' --with 'rfc8785>=0.1.4')

"${SEMANTICS_RUN[@]}" utils/benchmark_semantics.py validate \
  golden_al_distribution/v1/*.json

"${SEMANTICS_RUN[@]}" utils/benchmark_semantics.py resolve-curve \
  --curve-id qwen3-5-397b-a17b-nvfp4.mtp.native.speedbench-coding.v1 \
  --model-key qwen3.5-397b-a17b-nvfp4 \
  --thinking-state enabled --method mtp --variant native \
  --num-speculative-tokens 3 --allow-draft

"${SEMANTICS_RUN[@]}" utils/benchmark_semantics.py injections \
  --framework tensorrt-llm --role decode \
  --acceptance-length 3.5 --num-speculative-tokens 4
```

编写带占位身份字段的 YAML 或 JSON 后，使用 `stamp INPUT --output OUTPUT` 计算并校验 digest 与确定性的行为 ID。使用 `materialize CONTRACT --measurement throughput|accuracy --output OUTPUT` 生成准确的测量专用契约。重新运行 [`utils/migrate_golden_curves.py`](../utils/migrate_golden_curves.py)，可根据其显式元数据表和旧格式数值单元确定性地重新生成历史 v1 companion。

## 运行时产出与消费者规则

AgentX runner 会在 replay 前暂存并校验 `results/behavior_contract.json`。如果 `INFERENCEX_BEHAVIOR_CONTRACT` 指向由 producer 编写的 resolved 契约，runner 会将其物化为所需测量语义。否则，它会产出 partial 旧运行时快照，其中包含中心位置可观测的运行值与 `benchmark_command.txt` 的 digest；命令文本本身不会被嵌入，以免泄漏凭据或内部 endpoint。

`process_agentic_result.py` 会校验暂存文档，并把其中的 `behavior` 对象以及 `behavior_contract_digest` 嵌入 aggregate JSON。直接处理没有暂存收据的旧结果目录仍受支持，只会省略这两个字段。

消费者应当：

1. 使用严格加载器校验整份文档及其 digest。
2. 只有在 `status=resolved` 时，才将 digest 用作可比性 key。
3. 使用 `contract_digest` 比较计划行为，并单独检查 `runtime_verification`。
4. 将 `not_verified` 视为没有运行时结论，绝不能视作校验成功。
5. 仅按显式语义身份解析曲线，并验证所选 `curve_digest`。

当前 workflow/config matrix 尚未暴露一等的 behavior-contract 字段。因此，普通签入 recipe 会产出 partial 收据，除非其启动环境显式设置 `INFERENCEX_BEHAVIOR_CONTRACT`。这一限制会在 artifact 中明确可见，而不会隐藏在推断出的默认值后面。
