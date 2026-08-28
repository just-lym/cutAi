# 模块 3: 多 Agent 系统 (LangGraph)

## 架构概述

采用 **Supervisor + Specialists** 模式：
- **supervisor Agent** (qwen-max)：理解用户意图，动态分派任务给 Specialist，循环调度直到完成
- **subtitle Agent** (qwen-plus)：字幕分析、ASR、断句、纠错
- **audio Agent** (qwen-plus)：音效检测、音量分析
- **b-roll Agent** (qwen-max)：B-roll 位置识别、视频生成提示词
- **review Agent** (qwen-max)：合并所有建议、冲突检测、生成最终 EditPlan

图结构：
```
supervisor -> (条件路由) -> subtitle_agent / audio_agent / broll_agent -> supervisor (循环)
supervisor -> review -> END
supervisor -> respond -> END (直接回复)
```

## AgentState (共享状态)

```python
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]  # LangGraph 消息累积
    project_id: str
    project_dir: str
    timeline_version: int | None
    edit_plans: dict | None      # Review Agent 输出的最终计划
    agent_outputs: dict[str, Any] # 各 Specialist 的结构化输出
    awaiting_user: bool           # 是否需要用户确认
    total_costs: float            # 累计费用（元）
```

ChatDashScope 适配层
自定义 LangChain BaseChatModel，包装阿里 DashScope API，支持 tool calling。

关键点：

1. 继承 BaseChatModel，实现 _generate() 方法

2. 消息格式转换：LangChain Message -> DashScope format (system/user/assistant/tool)

3. Tool call 特别：DashScope 返回的 tool_calls 转为 LangChain AIMessage.tool_calls 格式

4. bind_tools() 方法：将 LangChain BaseTool 转为 Dash 的 function format

```python
class ChatDashScope(BaseChatModel):
    model_name: str = Field(default="qwen-max", alias="model")
    temperature: float = 0.7
    max_tokens: Optional[int] = None

    def _generate(self, messages, stop, run_manager, **kwargs) -> ChatResult:
        ds_messages = _messages_to_dashscope(messages)
        call_kwargs = {
            "model": self.model_name,
            "messages": ds_messages,
            "result_format": "message",
            "temperature": self.temperature,
        }
        if kwargs.get("tools"):
            call_kwargs["tools"] = _convert_tools_to_dashscope(kwargs["tools"])

        response = Generation.call(**call_kwargs)
        # 解析 response -> AIMessage(content, tool_calls)
        # 返回 ChatResult(generations=[ChatGeneration(message=ai_message)])
```
Supervisor Orchestrator
ReAct 风格编排，每轮只输出一个 JSON 决策：

System Prompt 核心：
```
你是视频剪辑 AI 平台的 Supervisor Agent。

可调度的专业 Agent：

- subtitle_agent：字幕分析、纠错、断句、翻译、ASR 生成

- audio_agent：音频分析、音效检测与删除、音量调整

- broll_agent：B-roll 素材推荐、插入位置识别、视频生成提示词

输出格式（严格 JSON）：
{"next": "subtitle_agent", "reason": "用户要求修正字幕"}
{"next": "review", "reason": "所有编辑建议已收集"}
{"next": "respond", "reason": "用户在询问功能，无需调度"}

```
路由函数解析 JSON 中的 `next` 字段，映射到对应节点。
```python
def build_supervisor_graph() -> StateGraph:
    graph = StateGraph(AgentState)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("subtitle_agent", run_subtitle_node)
    graph.add_node("audio_agent", run_audio_node)
    graph.add_node("broll_agent", run_broll_node)
    graph.add_node("review", run_review_node)
    graph.add_node("respond", respond_node)

    graph.set_entry_point("supervisor")
    graph.add_conditional_edges("supervisor", route_next, {...})
    # Specialist 循环回 supervisor
    graph.add_edge("subtitle_agent", "supervisor")
    graph.add_edge("audio_agent", "supervisor")
    graph.add_edge("broll_agent", "supervisor")

    # 终止节点
    graph.add_edge("review", END)
    graph.add_edge("respond", END)

    return graph.compile()
```
## Specialist Agents
每个 Specialist 使用 `langgraph.prebuilt.create_react_agent` 创建，配备专属工具集和 System Prompt。

## Subtitle Agent (qwen-plus)
- 工具：get_project_subtitles, get_project_assets, submit_asr, check_asr_status, parse_srt, probe_media
- 输出格式：
```json
{
  "summary": "修正了3处错别字，优化了5处断句",
  "operations": [
    {"type": "UPDATE_SUBTITLE", "cue_id": "...", "text": "...", "start_ms": ..., "end_ms": ...},
    {"type": "SPLIT_SUBTITLE", "cue_id": "...", "split_at_ms": ...},
    {"type": "MERGE_SUBTITLES", "cue_ids": ["...", "..."]}
  ]
}
```
### Audio Agent (qwen-plus)
- 工具：get_project_assets, get_project_timeline, detect_silence, extract_audio, probe_media
- 关键规则：DELETE_RANGE 必须基于 detect_silence 实际结果；区分“自然静音”(<1s) 和“无效静音”(>1s)
- 输出格式：
```json
{
  "summary": "检测到2段无效静音，建议整体音量+2db",
  "operations": [
    {"type": "DELETE_RANGE", "start_ms": 42000, "end_ms": 44000, "reason": "..."},
    {"type": "SET_VOLUME", "start_ms": 0, "end_ms": -1, "volume": 1.25},
    {"type": "FADE_IN", "start_ms": 0, "duration_ms": 500},
    {"type": "FADE_OUT", "start_ms": 170000, "duration_ms": 1000}
  ]
}
```
B-roll Agent (qwen-max)
- 工具：get_project_timeline, get_project_subtitles, get_project_assets, search_assets_by_embedding, generate_thumbnail, probe_media
- 任务：内容转折点、抽象概念处、避免重复覆盖、每段 3-6 秒
```json
{
  "summary": "建议在3个位置插入B-roll",
  "insertions": [
    {
      "position_ms": 32000,
      "duration_ms": 4000,
      "context": "讲到团队协作场景时",
      "visual_description": "现代化的开放式办公室...",
      "prompt_en": "Modern open-plan office, team brainstorming..., cinematic, 4K",
      "style_hints": "cinematic, warm",
      "audio_policy": "KEEP_ORIGINAL"
    }
  ]
}
```
## Review Agent (qwen-max)
- 工具：get_project_timeline, validate_edit_plan, apply_edit_plan
- 职责：合并所有 Agent 输出 → 时间顺序 → 冲突检测 → validate_edit_plan 校验 → 输出最终计划
冲突规则：

 - DELETE_RANGE 不能覆盖 INSERT_BROLL 位置
 - DELETE_RANGE 之间不能重叠
 - SET_VOLUME 区间必须在有效音轨范围内
 - 字幕修改不能指向已删除区间
- 输出格式：
```json
{
  "plan": {
    "summary": "删除2段静音，修改3条字幕，插入1段B-roll",
    "operations": [...],
    "conflicts": [],
    "requires_user_approval": true
  }
}
```
## Agent Tools (@tool 包装层)
将 app/tools/ 下的确定性工具包装为 LangChain @tool，供 ReAct 循环调用。

关键设计：

1. 同步执行（LangChain 默认） → 用 run_async() helper 在异步上下文中执行
2. 每个 tool 有详细中文 docstring，LLM 据此决定使用时机
3. 按agent分组为：SUBTITLE_TOOLS / AUDIO_TOOLS / BROLL_TOOLS / REVIEW_TOOLS

工具清单：
- **media**: probe_media, detect_silence, extract_audio, generate_thumbnails
- **subtitles**: submit_asr, check_asr_status, parse_srt
- **timeline**: validate_edit_plan, apply_edit_plan
- **data access**: get_project_subtitles, get_project_assets, get_project_timeline, search_assets_by_embedding

`_run_async` helper 处理 "sync context 中运行 async" 的问题：
```python
def _run_async(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result()
    else:
        return asyncio.run(coro)
```