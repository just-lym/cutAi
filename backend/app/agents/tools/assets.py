from langchain_core.tools import tool

from app.agents.tools.context import AgentToolContext, asset_summary
from app.agents.tools.schema import AgentTool


def build_asset_tools(context: AgentToolContext) -> list[AgentTool]:
    @tool("get_project_assets")
    async def get_project_assets(
        asset_type: str | None = None,
        completed_only: bool = True,
        include_paths: bool = False,
        limit: int = 30,
    ) -> dict:
        """列出项目素材。需要选择主视频、音频、图片或可插入素材时调用。"""
        assets = context.assets
        if asset_type:
            assets = [asset for asset in assets if asset.get("type") == asset_type]
        if completed_only:
            assets = [asset for asset in assets if asset.get("processing_status") == "COMPLETED"]
        return {
            "ok": True,
            "count": len(assets),
            "assets": [asset_summary(context, asset, include_paths) for asset in assets[:limit]],
        }

    @tool("search_project_assets")
    async def search_project_assets(query: str, asset_type: str | None = None, limit: int = 8) -> dict:
        """按文件名、类型和基础元数据搜索项目素材。B-roll 选择或素材定位时调用。"""
        query = str(query or "").lower()
        matches = []
        for asset in context.assets:
            if asset_type and asset.get("type") != asset_type:
                continue
            haystack = " ".join(
                str(value or "")
                for value in [
                    asset.get("id"),
                    asset.get("original_name"),
                    asset.get("type"),
                    asset.get("mime_type"),
                    asset.get("processing_status"),
                ]
            ).lower()
            score = 1 if query and query in haystack else 0
            if score or not query:
                matches.append((score, asset))
        matches.sort(key=lambda item: item[0], reverse=True)
        return {
            "ok": True,
            "count": len(matches),
            "assets": [asset_summary(context, asset) for _, asset in matches[:limit]],
        }

    return [get_project_assets, search_project_assets]
