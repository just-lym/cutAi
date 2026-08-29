# 模块 3: create_agent 多 Agent 系统

## 架构目标

用户用自然语言和 Agent 对话，下达剪辑目标；Agent 自主选择工具读取信息、分析素材、调用 FFmpeg，并输出结构化结果。

当前实现采用：

- LangGraph 编排多 Agent 节点
- LangChain `create_agent` 创建 Specialist Agent
- LangChain `@tool` 标记可调用工具
- Supervisor 根据意图识别做路由
- Specialist Agent 通过工具自主获取项目上下文和执行剪辑动作
- Review Agent 校验并合并最终 EditPlan

图结构：

```text
intent -> supervisor -> subtitle_agent / audio_agent / broll_agent / video_agent -> supervisor
supervisor -> review -> END
supervisor -> respond -> END
```

## 文件结构

```text
backend/app/agents/
  graph.py             # LangGraph 节点连接
  runtime.py           # create_agent 运行时、工具包装、结果解析
  intent.py            # 用户意图识别：基础操作 -> specialist
  supervisor.py        # 路由调度
  subtitle_agent.py    # create_subtitle_agent()
  audio_agent.py       # create_audio_agent()
  broll_agent.py       # create_broll_agent()
  video_agent.py       # create_video_agent()
  review_agent.py      # create_review_agent()
  respond_agent.py     # 无明确可执行操作时回复
  tools/
    __init__.py        # AgentToolbox
    schema.py          # AgentTool
    context.py         # 项目上下文和路径辅助
    timeline.py        # 时间线工具
    assets.py          # 素材工具
    subtitles.py       # 字幕工具
    ffmpeg.py          # FFmpeg 工具
backend/app/cloud_api/
  langchain_chat_model.py  # DashScope -> LangChain BaseChatModel 适配器
```

## create_agent 入口

每个 Specialist 文件都暴露 `create_xxx_agent()`，内部调用统一运行时：

```python
def create_video_agent(tools: Any) -> Any:
    return create_tool_agent(
        "video_agent",
        VIDEO_AGENT_PROMPT,
        tools,
        settings.cloud.specialist_model or settings.cloud.agent_model,
    )
```

`runtime.py` 中实际调用 LangChain API：

```python
from langchain.agents import create_agent

return create_agent(
    model=ChatDashScope(model=model, temperature=0.2),
    tools=create_langchain_tools(toolbox, agent_name),
    system_prompt=system_prompt,
    name=agent_name,
)
```

## 意图识别

`intent.py` 将用户输入识别成基础操作：

- `UPDATE_SUBTITLE` / `CREATE_SUBTITLE` -> `subtitle_agent`
- `DELETE_RANGE` / `SET_VOLUME` / `FADE_IN` / `FADE_OUT` -> `audio_agent`
- `INSERT_BROLL_OVERLAY` / `GENERATE_BROLL` -> `broll_agent`
- `CUT_SEGMENT` / `EXPORT_VIDEO` -> `video_agent`

Supervisor 根据 `AgentState.intent.specialist_agents` 决定下一步调度哪个 Agent。真正的信息获取和工具选择由 Specialist Agent 自己完成。

## 工具分组

工具必须使用 LangChain 原生 `@tool` 标记，不使用自定义伪工具对象，也不通过 `StructuredTool.from_function` 临时包一层。

### timeline

- `get_project_timeline`
- `validate_edit_operations`

### assets

- `get_project_assets`
- `search_project_assets`

### subtitles

- `get_project_subtitles`

### ffmpeg

- `ffmpeg_probe_asset`
- `ffmpeg_detect_silence`
- `ffmpeg_cut_segment`
- `ffmpeg_remove_ranges`

FFmpeg 工具会真实调用本地 `ffmpeg/ffprobe`，并把输出文件写入：

```text
{project_dir}/agent_outputs/
```

## Agent 职责

### Subtitle Agent

通过 `create_agent` 自主调用字幕、时间线、素材和媒体探测工具，输出 `UPDATE_SUBTITLE` 操作。

### Audio Agent

通过 `ffmpeg_detect_silence` 检测静音。`DELETE_RANGE` 必须来自真实工具结果。用户要求直接剪出文件时，可继续调用 `ffmpeg_remove_ranges`。

### B-roll Agent

读取时间线、字幕和素材，选择已有素材生成 `INSERT_BROLL_OVERLAY`，或返回无法插入的原因。

### Video Agent

处理“截取 10 秒到 20 秒”“剪出前 5 秒”“导出片段”等请求，调用 `ffmpeg_cut_segment` 或 `ffmpeg_remove_ranges` 输出文件。

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

1. 用户通过自然语言给 Agent 下达目标。
2. Specialist Agent 用 `create_agent` 创建，并在工具循环中自主选择工具。
3. 项目上下文不预先塞进 prompt；Agent 需要什么就调用工具取什么。
4. 工具按功能分文件，FFmpeg 剪辑能力集中在 `agents/tools/ffmpeg.py` 和底层 `app/tools/media_tools.py`。
5. Review Agent 负责校验和合并，最终写入等待审批的 EditPlan。
