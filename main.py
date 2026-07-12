"""AstrBot 插件：随机表情包（astrbot_plugin_randommeme）。

功能：
- 用户发送关键词（精确匹配，前后空格忽略）从对应组别目录抽一张图片。
- 同一组别内一整轮抽完才洗牌，全局共享抽取池。
- 支持多组别 / 别名 / 每个组别独立设置"需要 @/唤醒"。
- WebUI / Plugin Page 提供组别 CRUD、批量上传、删除图片、重置抽取序列。
- 帮助类指令: ``随机meme`` / ``随机表情`` / ``包帮助``。
"""

from __future__ import annotations

import logging

from astrbot.api.event import filter
from astrbot.api.star import Context, Star, register
from astrbot.core import AstrBotConfig
from astrbot.core.message.components import Image as CompImage
from astrbot.core.platform import AstrMessageEvent
from astrbot.core.star.filter.event_message_type import EventMessageType

from .core.api import register_web_apis
from .core.manager import MemeManager
from .core.storage import is_image_filename

logger = logging.getLogger(__name__)


@register(
    "astrbot_plugin_randommeme",
    "konley",
    "随机抽图表情包插件：关键词触发，按组别从不重复池中抽取一张图片发送",
    version="1.0.0",
)
class RandomMemePlugin(Star):
    """Top-level Star registering the plugin with AstrBot."""

    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.conf = config
        gif_support = bool(self.conf.get("gif_support", True))
        self.manager = MemeManager(gif_support=gif_support)
        self._web_apis_registered = False

    # --------------------------------------------------------- lifecycle

    async def initialize(self) -> None:
        await self.manager.load()
        self._register_web_apis_safe()
        logger.info(
            "[astrbot_plugin_randommeme] initialized; groups=%d",
            len(self.manager.list_groups()),
        )

    async def terminate(self) -> None:
        self._web_apis_registered = False
        logger.info("[astrbot_plugin_randommeme] terminated")

    # --------------------------------------------------------- main hook

    @filter.event_message_type(EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        text = (getattr(event, "message_str", "") or "").strip()
        if not text or not self._should_handle(event, text):
            return

        keyword = self._strip_prefix(text)
        group = self.manager.match_group(keyword)
        if not group:
            return

        if group.require_wake and not self._is_woken(event, text):
            yield event.plain_result(f"触发 {group.name} 需要 @机器人 或唤醒前缀")
            return

        picked = await self.manager.draw(group.name)
        if not picked:
            yield event.plain_result(
                f"组别 {group.name} 里还没有图片，先去 WebUI 上传几张吧"
            )
            return

        logger.info("[astrbot_plugin_randommeme] picked %s for %s", picked, group.name)
        chain = self._build_image_chain(picked)
        if chain is not None:
            yield event.chain_result(chain)
        else:
            yield event.plain_result(f"图片路径不合法: {picked}")

    # --------------------------------------------------------- command hooks

    @filter.command("随机meme", alias={"随机表情", "包帮助"})
    async def cmd_help(self, event: AstrMessageEvent):
        yield event.plain_result(
            "\n".join(
                [
                    "随机表情包 · 使用说明",
                    "1. 直接发送组别名 → 抽一张图（精确匹配，前后空格忽略）。",
                    "2. 小工具:",
                    "   - 随机meme列表：列出所有组别",
                    "   - 随机meme详情 <组别>：查看组别",
                    "   - 随机meme重置 [组别]：重置抽取序列（不带组别 = 清空全部）",
                    "   - 随机meme禁用 <组别> / 随机meme启用 <组别>：开关某个组别",
                    "3. 详细管理请到 WebUI → 插件 → 随机表情包 页。",
                ]
            )
        )

    @filter.command("随机meme列表", alias={"meme列表", "表情列表"})
    async def cmd_list_groups(self, event: AstrMessageEvent):
        groups = self.manager.list_groups()
        if not groups:
            yield event.plain_result("还没有任何组别，先去 WebUI 创建几个吧。")
            return
        lines = ["组别列表:"]
        for g in groups:
            count = self.manager.image_count(g.name)
            alias_text = ", ".join(g.aliases) if g.aliases else "-"
            status = "启用" if g.enabled else "禁用"
            wake = "(需唤醒)" if g.require_wake else ""
            lines.append(f"- {g.name}{wake} [{status}] 图:{count} | 别名:{alias_text}")
        yield event.plain_result("\n".join(lines))

    @filter.command("随机meme详情", alias={"meme详情", "表情详情"})
    async def cmd_group_detail(self, event: AstrMessageEvent, name: str | None = None):
        if not name:
            yield event.plain_result("用法:随机meme详情 <组别名>")
            return
        g = self.manager.get_group(name)
        if not g:
            yield event.plain_result(f"未找到组别: {name}")
            return
        yield event.plain_result(
            "\n".join(
                [
                    f"组别: {g.name}",
                    f"别名: {', '.join(g.aliases) or '-'}",
                    f"状态: {'启用' if g.enabled else '禁用'}",
                    f"需唤醒: {'是' if g.require_wake else '否'}",
                    f"图片数: {self.manager.image_count(g.name)}",
                ]
            )
        )

    @filter.command("随机meme重置", alias={"meme重置", "表情重置"})
    async def cmd_reset_group(self, event: AstrMessageEvent, name: str | None = None):
        if name:
            g = self.manager.get_group(name)
            if not g:
                yield event.plain_result(f"未找到组别: {name}")
                return
            await self.manager.reset_history(g.name)
            yield event.plain_result(f"已重置 {g.name} 的抽取序列。")
            return
        count = await self.manager.reset_history(None)
        yield event.plain_result(f"已重置全部 {count} 个组别的抽取序列。")

    @filter.command("随机meme禁用", alias={"meme禁用", "禁用表情"})
    async def cmd_disable_group(self, event: AstrMessageEvent, name: str | None = None):
        if not name:
            yield event.plain_result("用法:随机meme禁用 <组别名>")
            return
        try:
            g = await self.manager.update_group(name, enabled=False)
        except ValueError as exc:
            yield event.plain_result(str(exc))
            return
        yield event.plain_result(f"已禁用 {g.name}")

    @filter.command("随机meme启用", alias={"meme启用", "启用表情"})
    async def cmd_enable_group(self, event: AstrMessageEvent, name: str | None = None):
        if not name:
            yield event.plain_result("用法:随机meme启用 <组别名>")
            return
        try:
            g = await self.manager.update_group(name, enabled=True)
        except ValueError as exc:
            yield event.plain_result(str(exc))
            return
        yield event.plain_result(f"已启用 {g.name}")

    # --------------------------------------------------------- helpers

    def _register_web_apis_safe(self) -> None:
        if self._web_apis_registered:
            return
        try:
            register_web_apis(self.context, self.manager)
            self._web_apis_registered = True
        except Exception as exc:  # pragma: no cover - guarded
            logger.exception("注册 Web API 失败: %s", exc)

    def _should_handle(self, event: AstrMessageEvent, text: str) -> bool:
        extra_prefix = str(self.conf.get("extra_prefix") or "")
        if extra_prefix and text.startswith(extra_prefix):
            return True
        if not bool(self.conf.get("need_prefix", True)):
            return True
        return bool(getattr(event, "is_at_or_wake_command", False))

    def _strip_prefix(self, text: str) -> str:
        extra = str(self.conf.get("extra_prefix") or "")
        if extra and text.startswith(extra):
            return text[len(extra) :].strip()
        return text

    def _is_woken(self, event: AstrMessageEvent, text: str) -> bool:
        extra = str(self.conf.get("extra_prefix") or "")
        if extra and text.startswith(extra):
            return True
        return bool(getattr(event, "is_at_or_wake_command", False))

    def _build_image_chain(self, path: str) -> list | None:
        if not is_image_filename(path, gif_support=self.manager.gif_support):
            return None
        return [CompImage.fromFileSystem(path)]
