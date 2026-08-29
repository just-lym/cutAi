# 模块 5: API 路由层 (FastAPI)

## projects.py - 项目 CRUD
...

POST /api/projects          创建项目 {name, width=1920, height=1080, frame_rate=30}
GET  /api/projects          列表 (默认 ARCHIVED, 按 updated_at desc)
GET  /api/projects/{id}     获取单个
DELETE /api/projects/{id}   归档 (设置 status=ARCHIVED)

## assets.py - 素材管理
...

POST /api/projects/{id}/assets/import   本地路径导入 (copy 到 projects/{id}/originals/)
POST /api/projects/{id}/assets/upload   文件上传 (multipart/form-data)
GET  /api/projects/{id}/assets          列表
GET  /api/assets/{id}/status           处理状态

素材类型自动识别：按文件扩展名判断
- VIDEO: .mp4, .mov, .webm, .m4v
- AUDIO: .mp3, .wav, .m4a, .flac
- IMAGE: .png, .jpg, .jpeg, .webp
- SUBTITLE: .srt, .vtt, .ass, .ssa

文件存储路径规则：`{data_root}/projects/{project_id}/originals/{filename}`

## timelines.py - 时间轴版本管理
...

GET  /api/projects/{id}/timeline             获取最新版本
POST /api/projects/{id}/timeline/commit      提交新版本 (operations list)
GET  /api/projects/{id}/timeline/versions    版本历史列表
POST /api/projects/{id}/timeline/restore     恢复到某版本 (创建新版本, timeline.json 拷贝自目标版本)

版本递增逻辑：新版本号 = 旧版本号 + 1, parent_version_id 指向旧一个。

## agents.py - Agent 会话与审批
...

POST   /api/agent/runs/{run_id}/approve      批准继续计划 (支持部分审批)
POST   /api/agent/runs/{run_id}/reject       拒绝继续计划
POST   /api/agent/runs/{run_id}/undo         撤回最后一次已应用的 Agent 计划

## 流式 SSE 端点
```
POST /api/projects/{id}/agent/stream     SSE 流式 Agent 响应
```
事件类型：
| event | data | 说明 |
|-------|------|------|
| thinking | `{"agent": "main_agent"}` | Agent 思考中 |
| status | `{"agent": "main_agent", "detail": "..."}` | 长任务心跳 |
| progress | `{"stage": "...", "progress": 0.5}` | 模型/工具/保存阶段进度 |
| tool_call | `{"tool": "...", "detail": "..."}` | Agent 工具调用轨迹 |
| preview_ready | `{"path": "..."}` | FFmpeg 预览/输出文件就绪 |
| token | `{"content": "..."}` | 回复 token (逐字) |
| trace | `{"title": "...", "detail": "...", "data": {...}}` | Agent 执行轨迹 |
| plan | `{"summary, operations, conflicts"}` | 最终编辑计划 |
| done | `{"session_id, total_cost"}` | 流结束 |
| error | `{"message": "..."}` | 错误 |

使用 `graph.astream()` 输出 Main Agent、专家 Agent、Review 轨迹；长任务通过 status/progress/tool_call 保持前端有反馈。
前端通过 fetch + ReadableStream 消费，支持 AbortController 中断。

### 部分审批 (approve endpoint)

请求体 (可选，向后兼容):
```json
{
  "approved_indices": [0, 2, 3],
  "rejected_indices": [1]
}
```
- body 为空或 approved_indices 为 null - 全量批准 (原有行为)
- 提供 indices - 部分审批，status 设为 PARTIALLY_APPROVED
- 返回 {ok, applied_count, rejected_count, plan_status}
### 核心流程 (stream_agent_message):
1. 查找或创建 ACTIVE 状态的 AgentSession
2. 构建 LangGraph Agentic runtime，Main Creative Agent 使用 `create_agent` ReAct 模式
3. 初始化 AgentState (messages=[HumanMessage], project_id, ...)
4. `graph.astream(initial_state)` - 流式输出 Main Agent、工具调用、专家 Agent 和 Review 轨迹
5. 提取最终 plan
6. 更新 session 费用
7. 如果有 edit_plan + awaiting_user=True - 创建 EditPlan 记录 (WAITING_USER)
8. 返回 plan/token/done SSE 事件
### Approve 执行链路:
1. 收集 approved_indices 对应的 operations
2. 调用 `execute_edit_plan(project_id, operations)` - 生成新 TimelineVersion
3. 更新 plan_status APPROVED/PARTIALLY_APPROVED
4. WebSocket broadcast `timeline_updated` 消息
5. 返回 `{ok, applied_count, rejected_count, plan_status, timeline_version}`
6. 失败 -> ExecutionError -> 返回 500, plan 状态不变

### Undo 执行链路:
1. 仅允许撤回 status=APPLIED 的计划
2. 查找 `change_summary == Applied AI edit plan {plan_id}` 的时间线版本
3. 只有该版本仍是最新版本时自动撤回
4. 基于 `base_timeline_version` 创建新的恢复版本
5. WebSocket broadcast `timeline_updated`
## WebSocket 端点
```
WS /ws/projects/{project_id}  实时事件推送
```

事件类型：job_progress (流水线步骤进度), timeline_updated (新版本生成)

## subtitles.py - 字幕 CRUD
```
GET   /api/projects/{id}/subtitles          列表 (按 start_ms 排序, 来自最新 TimelineVersion 的 SUBTITLE 轨道)
PUT   /api/projects/{id}/subtitles/{cue_id} 更新字幕 (text, start_ms, end_ms, speaker)
DELETE /api/projects/{id}/subtitles/{cue_id} 删除字幕
```



查询链路：Project -> 最新 TimelineVersion -> Track(type=SUBTITLE) -> SubtitleCue

更新/删除时校验 cue 归属关系：cue.track -> track.timeline_version.project_id == path project_id

## broll.py - B-roll 管理
```
POST   /api/projects/{id}/broll/analyze       分析 B-roll 插入位置 (调用 broll_agent)
POST   /api/projects/{id}/broll/search-library 素材库语义搜索 (Chroma embedding_store)
POST   /api/projects/{id}/broll/select        选择并插入 B-roll -> 返回 operation

```


### analyze 流程
1. 获取最新 TimelineVersion + SUBTITLE 轨道 cues
2. 将字幕文本传给 broll_agent (LangGraph ReAct)
3. 解析 agent 输出的 insertions JSON
4. 返回 `{positions: BrollPosition[]}`

### search-library 流程
1. 调用 DashScope Text-embedding-v3 生成 query 向量
2. embedding_store.search_similar(project_id, query_embedding, top_k)
3. 通过 asset_id 查询 Asset 记录补充元数据
4. 返回 `{candidates: BrollCandidate[]}` (score = 1 - cosine_distance)

### select 流程
1. 验证 candidate asset 属于该 project
2. 构造 `{type: "INSERT_BROLL_OVERLAY", asset_id, position_ms, duration_ms}`
3. 返回 `{ok: true, operation: {...}}`


## render.py - 渲染任务

```
POST   /api/projects/{id}/previews     创建预览渲染任务 (PREVIEW_RENDER)
POST   /api/projects/{id}/exports      创建最终导出任务 (FINAL_RENDER)
GET    /api/jobs/{job_id}              任务状态查询
POST   /api/jobs/{job_id}/cancel       取消任务
```
## usage.py - 用量统计

```
GET    /api/usage/summary             本月汇总 (total_cost, tokens, audio_ms, budget_remaining)
GET    /api/usage/detail              明细列表 (支持 start/end 日期过滤, limit=200)
GET    /api/config/budget             预算配置
```

月度汇总计算：
- 从 cloud_api_usage 表 WHERE created_at >= 当月1日 00:00
- budget_remaining = max(0, monthly_budget - total_cost)
