# CY-152 Windows GPU 分析冒烟

固定章节 `rain-alley-ch1` 在本机 `qwen3.5:9b` 上产出了能解析成 Analysis Schema 的 JSON。两条黄金事实没有对上，所以这不是整份 golden 全通过。

仓库默认仍是 `LNS_EXECUTION_PROFILE=cpu-dev`。

## 环境

- 日期：2026-10-02
- 主机：Windows，NVIDIA GeForce RTX 5070 Ti，驱动 616.64
- 工作区 HEAD：`943d726259ef825a4d562dbf2b905cb0adeab499`
- 模型：`qwen3.5:9b`，id `6488c96fa5fa`，Q4_K_M，9.7B。没有新拉模型。

## 命令

在 `backend` 目录：

```powershell
$env:LNS_EXECUTION_PROFILE = "windows-gpu"
$env:LNS_OLLAMA_SMOKE = "1"
uv run python -m app.eval.analysis_golden --live
Remove-Item Env:LNS_EXECUTION_PROFILE
Remove-Item Env:LNS_OLLAMA_SMOKE
```

## 结果

进程退出码 1，耗时约 17s。Fixture 契约本身通过。真实模型输出已解析，但缺：

- `foreshadowing.status` 没有 `planted`
- `world_facts.fact` 没有关键词「雨巷」

人物、地点、事件、关系、时间线和视角这些检查没有报缺。非法 JSON 没有进入后续比对。
