# CY-202 / CY-266 Windows GPU 十八章基线

这次是本机 RTX 5070 Ti 上的真实模型跑通，不是 FakeEmbedding，也不是 Milvus mock。

仓库默认仍是 `LNS_EXECUTION_PROFILE=cpu-dev`。下面的命令只在当次进程里临时设成 `windows-gpu`，跑完已清掉。

## 环境

- 日期：2026-10-02
- 主机：Windows，NVIDIA GeForce RTX 5070 Ti，驱动 616.64，显存 16303 MiB
- 工作区 HEAD：`943d726259ef825a4d562dbf2b905cb0adeab499`
- 基线测试还在未提交的工作区里，不在上述 commit 中
- Milvus：`127.0.0.1:19530`，跑完后 collection 列表为空（测试结束时删除了新建集合）

## 模型

没有新拉模型。

```text
qwen3.5:9b              6488c96fa5fa    6.6 GB
qwen3-embedding:0.6b    ac6da0dfba84    639 MB
```

`qwen3-embedding:0.6b`：architecture qwen3，parameters 595.78M，embedding length 1024，quantization Q8_0。GGUF blob `sha256-06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439`。

`qwen3.5:9b`：architecture qwen35，parameters 9.7B，quantization Q4_K_M。

## 命令

在 `backend` 目录：

```powershell
$env:LNS_EXECUTION_PROFILE = "windows-gpu"
uv run pytest tests/test_v04_e2e.py::test_eighteen_chapter_windows_gpu_baseline -q --tb=short -s
Remove-Item Env:LNS_EXECUTION_PROFILE
```

语料是检索基准的前 6 章原文，加上 12 章无关短句，共 18 章。另有一本小说和一条草稿，用来检查隔离。初始化走真实 `qwen3.5:9b` 分析，再切块、用 `qwen3-embedding:0.6b` 写入 Milvus。

## 结果

pytest：1 passed，75.58s。

- 18 章初始化到 `ready`。续写门槛文案是「初始化已完成，可以阅读，也可以进入续写。」
- 本章块数 18。删除正在使用的 collection 后，从 SQLite 重建，块 id 不变。
- 重建后向量数 19（18 章加另一本小说的 1 块），维度 1024。
- 草稿正文不在 Canon 块里。另一本小说的块在集合里，但不出现在当前小说的检索结果里。
- Debug 对「林深住在哪里」给出了选中证据，原因是 `selected`。
- 边界问句「海底龙宫的钥匙在哪」也有候选和状态，结果仍只属于当前小说。

基准（`retrieval-benchmark.v1`，scoring `retrieval-scoring.v1`）：

- embedding profile：`2a4ba5ef13580c6ef02b0a0aaeb12174ef96bcec6ed498dc19dddb0ebb70e887`
- index version：`47a11d0013cabaf6e3a661a3a8e1bfdc`
- Recall@5 = Recall@10 = source hit rate = 0.333
- 人物、关系：命中（章节 1、2）
- 未命中：`event-umbrella` 实际章节 [2, 1]；`location-lane` 实际为空；`foreshadow-name` 实际 [2, 1]；`timeline-spring` 实际 [2, 1]

地点查询带了 `locations: ["雨巷"]`，检索会把它变成 Milvus 的地点过滤。分析如果没把「雨巷」写进该块的元数据，过滤后就是空结果。这是这条基线要留着的对照，不是 v1.0 发布阈值。

## 还没做

- 这些数字还没有对应的 commit SHA。
- 没有在浏览器里对这 18 章点「开始初始化」。进度页、暂停、继续、取消、重试此前已在浏览器里看过；这次 GPU 证据是同一套 Coordinator 在真实模型上跑到 Ready。
