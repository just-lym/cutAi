# 模块 3: Agentic 多 Agent 系统

## 架构目标

用户用自然语言和 Main Creative Agent 对话，下达剪辑目标；Main Agent 自主读取项目状态、判断创作方向、选择工具，并在需要时把专业任务委托给子 Agent。系统不使用关键词意图识别做固定路由。

当前实现采用：

- LangGraph 管理运行状态、流式输出、Review 和可审批 EditPlan。
- LangChain `create_agent` 创建 Main Agent 和 Specialist Agent。
- LangChain `@tool` 标记所有可调用工具。
- Main Agent 通过工具自主读取时间线、素材、字幕和媒体探测信息。
- Main Agent 通过委托工具调用 Audio、Video、Subtitle、B-roll 子 Agent。
- Specialist Agent 通过自己的工具完成专业分析或 FFmpeg 文件输出。
- Review Agent 校验并合并最终 EditPlan。

图结构：

```text
main_agent -> review -> END
main_agent -> END
```

`main_agent -> END` 用于纯讨论、创作建议或无法生成可靠操作的情况。

## 文件结构

```text
backend/app/agents/
  graph.py             # LangGraph 节点连接
  main_agent.py        # create_agent 主创作 Agent
  runtime.py           # create_agent 运行时、结果解析、工具轨迹
  subtitle_agent.py    # create_subtitle_agent()
  audio_agent.py       # create_audio_agent()
  broll_agent.py       # create_broll_agent()
  video_agent.py       # create_video_agent()
  review_agent.py      # create_review_agent()
  tools/
    __init__.py        # AgentToolbox
    schema.py          # AgentTool
    context.py         # 项目上下文和路径辅助
    timeline.py        # 时间线工具
    assets.py          # 素材工具
    subtitles.py       # 字幕工具
    ffmpeg.py          # FFmpeg 工具
    delegation.py      # 子 Agent 委托工具
backend/app/cloud_api/
  langchain_chat_model.py  # DashScope -> LangChain BaseChatModel 适配器
```

## Main Agent

Main Agent 是用户直接对话的创作 agent。它可以调用：

- `get_project_timeline`
- `get_project_assets`
- `get_project_subtitles`
- `search_project_assets`
- `ffmpeg_probe_asset`
- `delegate_to_audio_agent`
- `delegate_to_video_agent`
- `delegate_to_subtitle_agent`
- `delegate_to_broll_agent`

Main Agent 不靠意图识别结果决定路线。它根据用户目标和工具观察结果，自主决定是否读取更多上下文、是否委托子 Agent、是否进入 Review。

## create_agent 入口

每个 Agent 文件都暴露 `create_xxx_agent()`，内部使用 LangChain 原生 `create_agent`。工具使用 `@tool` 定义，不使用伪工具对象。

示例：

```python
from langchain.agents import create_agent

return create_agent(
    model=ChatDashScope(model=model, temperature=0.2),
    tools=[toolbox.get(tool_name) for tool_name in toolbox.names_for(agent_name)],
    system_prompt=system_prompt,
    name=agent_name,
)
```

## 委托工具

`tools/delegation.py` 提供 Main Agent 可调用的子 Agent 工具：

- `delegate_to_audio_agent`
- `delegate_to_video_agent`
- `delegate_to_subtitle_agent`
- `delegate_to_broll_agent`

每个委托工具接收自然语言 `task`，再调用对应 Specialist Agent。子 Agent 会自主调用自己的工具并返回结构化输出。Main Agent 不需要预先把完整上下文塞给子 Agent；子 Agent 需要什么信息就自己调工具获取。

## FFmpeg 工具

FFmpeg 工具会真实调用本地 `ffmpeg/ffprobe`，并把输出文件写入：

```text
{project_dir}/agent_outputs/
```

当前工具：

- `ffmpeg_probe_asset`
- `ffmpeg_detect_silence`
- `ffmpeg_cut_segment`
- `ffmpeg_remove_ranges`
- `ffmpeg_transcode_preview`
- `ffmpeg_change_volume`
- `ffmpeg_apply_audio_fade`
- `ffmpeg_extract_frame`
- `ffmpeg_overlay_asset`

这些工具是高层受控命令，不向 Agent 暴露任意 shell。

## Agent 职责

### Audio Agent

通过 `ffmpeg_detect_silence` 检测静音和停顿。需要输出文件时调用 `ffmpeg_remove_ranges`。音量和淡入淡出任务使用 `ffmpeg_change_volume`、`ffmpeg_apply_audio_fade`。

### Video Agent

处理截取、删除区间、转码预览、抽帧等任务，使用 `ffmpeg_cut_segment`、`ffmpeg_remove_ranges`、`ffmpeg_transcode_preview`、`ffmpeg_extract_frame`。

### Subtitle Agent

读取字幕、时间线、素材和媒体探测信息，输出 `UPDATE_SUBTITLE` 操作。

### B-roll Agent

读取时间线、字幕和素材，选择已有素材生成 `INSERT_BROLL_OVERLAY`，并可用 `ffmpeg_overlay_asset` 生成覆盖预览。

### Review Agent

读取 Specialist 输出，调用 `validate_edit_operations` 校验候选操作，生成最终计划：

```json
{
  "plan": {
    "summary": "删除2段静音，插入1段B-roll",
    "operations": [],
    "conflicts": [],
    "requires_user_approval": true
  }
}
```

## 设计原则

1. 用户只和 Main Creative Agent 对话。
2. Main Agent 自主选择工具和子 Agent，不使用关键词意图识别路由。
3. Specialist Agent 用 `create_agent` 创建，并在工具循环中自主选择工具。
4. 工具按功能分文件，FFmpeg 剪辑能力集中在 `agents/tools/ffmpeg.py` 和底层 `app/tools/media_tools.py`。
5. Timeline 修改必须进入等待审批的 EditPlan，应用后产生新 timeline version，天然支持回滚。
