# CY-182 Windows GPU embedding smoke

Fake provider 和 `cpu-dev` 下的契约测试不是这次验收证据。下面的数字来自本机 RTX 5070 Ti 上的 `qwen3-embedding:0.6b`。

仓库默认仍是 `LNS_EXECUTION_PROFILE=cpu-dev`。这次只在命令里临时设成 `windows-gpu`。

## 环境

- 日期：2026-10-02
- 主机：Windows，NVIDIA GeForce RTX 5070 Ti，驱动 616.64，显存 16303 MiB
- 工作区 HEAD：`943d726259ef825a4d562dbf2b905cb0adeab499`
- Embedding 适配器和 smoke 测试还在未提交的工作区里，不在上述 commit 中

## 模型

```text
ollama list
qwen3-embedding:0.6b    ac6da0dfba84    639 MB
```

`ollama show qwen3-embedding:0.6b`：

- architecture: qwen3
- parameters: 595.78M
- embedding length: 1024
- quantization: Q8_0
- GGUF blob: `sha256-06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439`

没有新拉模型。

## 命令

在 `backend` 目录：

```powershell
ollama stop qwen3-embedding:0.6b
$env:LNS_EXECUTION_PROFILE = "windows-gpu"
uv run pytest tests/test_embeddings.py::test_real_qwen_embedding_smoke -q --tb=short
ollama ps
```

## 结果

- smoke：1 passed（约 2.9s，含模型装入显存）
- 维度：1024，与 `ollama show` 的 embedding length 一致
- 模型装入后的两次相同 query：向量逐元素相同
- 刚装入时的第一次向量和随后稳定向量的余弦相似度为 0.999861，不完全相同。测试要求装入后的重复调用一致，并要求这次余弦相似度不低于 0.999
- `ollama ps`：`qwen3-embedding:0.6b`，`100% GPU`，约 3.8 GB
- 额外观察，不是门禁：模型已在显存中时，32 条短句一次 `embed_documents` 用了 9.976s，约 3.2 条/秒

## 尚未验证

- 这些结果还没有对应的 commit SHA
- 没有跑 Milvus 写入、检索 Recall，也没有把这次吞吐当作性能指标
