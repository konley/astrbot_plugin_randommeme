"""AstrBot 插件：随机表情包（astrbot_plugin_randommeme）。

功能：
- 用户发送关键词从对应组别目录抽一张图片。
- 同一组别内一整轮抽完才洗牌，全局共享抽取池。
- 支持多组别 / 别名 / 每个组别独立设置「需要 @/唤醒」。
- WebUI / Plugin Page 提供组别 CRUD、批量上传等。
- 聊天精简指令组：表情 帮助 / 列表 / 加 / 新 / 别名。

注意：不要使用 ``from __future__ import annotations``。
AstrBot 的 ``GreedyStr`` 依赖 ``inspect`` 拿到真实类对象（``is GreedyStr``），
future annotations 会把注解变成字符串，导致只吃第一个参数、后续别名被清空。
"""

import logging
import re
import time
from typing import Optional

from astrbot.api.event import filter
from astrbot.api.star import Context, Star, register
from astrbot.core import AstrBotConfig
from astrbot.core.message.components import Image as CompImage, Reply
from astrbot.core.platform import AstrMessageEvent
from astrbot.core.star.filter.command import GreedyStr
from astrbot.core.star.filter.event_message_type import EventMessageType

from .core.api import WebApiMixin
from .core.images import collect_image_components, extract_image_uploads
from .core.manager import MemeManager
from .core.storage import is_image_filename

logger = logging.getLogger(__name__)

HELP_TEXT = "\n".join(
    [
        "随机表情包 · 指令",
        "看库 → 表情 列表",
        "灌图 → 表情 加 <组别>（带图或回复带图）",
        "新组 → 表情 新 <名称> [别名…]",
        "改名 → 表情 别名 <组别> <别名…>",
        "出图 → 直接发送组别名/别名",
        "帮助 → 表情 帮助",
        "",
        "说明：加 / 新 / 别名 为管理指令；开启「仅管理员可管理」后仅 AstrBot 管理员可用。",
        "出图不受该开关影响。详细管理也可在 WebUI → 随机表情包 页完成。",
    ]
)

_UPLOAD_WAIT_SECONDS = 30


def _split_tokens(text: Optional[str]) -> list:
    if not text:
        return []
    return [p for p in str(text).strip().split() if p]


def _message_tail_after_subcommand(event: AstrMessageEvent, subcommand: str) -> str:
    """从完整消息里截取「表情 <子命令>」之后的参数（GreedyStr 失效时的兜底）。"""
    try:
        raw = event.get_message_str() or ""
    except Exception:
        raw = getattr(event, "message_str", "") or ""
    msg = re.sub(r"\s+", " ", raw.strip())
    # 去掉常见唤醒前缀 /
    if msg.startswith("/"):
        msg = msg[1:].lstrip()
    prefixes = (
        f"表情 {subcommand}",
        f"表情{subcommand}",
    )
    for p in prefixes:
        if msg == p:
            return ""
        if msg.startswith(p + " "):
            return msg[len(p) :].strip()
    return ""


@register(
    "astrbot_plugin_randommeme",
    "konley",
    "随机抽图表情包插件：关键词触发，按组别从不重复池中抽取一张图片发送",
    version="1.1.1",
)
class RandomMemePlugin(Star, WebApiMixin):
    """Top-level Star registering the plugin with AstrBot."""

    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.conf = config
        gif_support = bool(self.conf.get("gif_support", True))
        exact_match = bool(self.conf.get("exact_match", False))
        self.manager = MemeManager(gif_support=gif_support, exact_match=exact_match)
        self._last_trigger = {}  # type: dict
        self._upload_wait = {}  # type: dict
        self._register_web_apis()

    # --------------------------------------------------------- lifecycle

    async def initialize(self) -> None:
        await self.manager.load()
        logger.info(
            "[astrbot_plugin_randommeme] initialized; groups=%d",
            len(self.manager.list_groups()),
        )

    async def terminate(self) -> None:
        logger.info("[astrbot_plugin_randommeme] terminated")

    # --------------------------------------------------------- config helpers

    def _cooldown_seconds(self) -> int:
        return int(self.conf.get("cooldown_seconds", 0))

    def _reply_mode(self) -> bool:
        return bool(self.conf.get("reply_mode", False))

    def _admin_only_manage(self) -> bool:
        """开启后聊天管理指令仅管理员可用；出图不受影响。WebUI 始终可用。"""
        return bool(self.conf.get("admin_only_manage", True))

    def _manage_allowed(self, event: AstrMessageEvent) -> bool:
        if not self._admin_only_manage():
            return True
        try:
            return bool(event.is_admin())
        except Exception:
            return False

    def _deny_manage_msg(self) -> str:
        return (
            "管理指令仅 AstrBot 管理员可用"
            "（插件配置「仅管理员可管理」已开启）。出图不受影响。"
        )

    def _user_key(self, event: AstrMessageEvent) -> str:
        session = getattr(event, "session_id", "") or ""
        sender = ""
        try:
            sender = event.get_sender_id() or ""
        except Exception:
            sender = ""
        return f"{session}_{sender}"

    # --------------------------------------------------------- 抽图 + 等图入库

    @filter.event_message_type(EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        async for result in self._try_consume_upload_wait(event):
            yield result
            return

        text = (getattr(event, "message_str", "") or "").strip()
        if not text or not self._should_handle(event, text):
            return

        keyword = self._strip_prefix(text)
        if keyword == "表情" or keyword.startswith("表情 "):
            return

        group = self.manager.match_group(keyword)
        if not group:
            return

        if group.require_wake and not self._is_woken(event, text):
            yield event.plain_result(f"触发 {group.name} 需要 @机器人 或唤醒前缀")
            return

        cd = self._cooldown_seconds()
        if cd > 0:
            origin = getattr(event, "unified_msg_origin", "") or ""
            now = time.time()
            last = self._last_trigger.get(origin, 0.0)
            elapsed = now - last
            if elapsed < cd:
                remain = int(cd - elapsed)
                yield event.plain_result(f"冷却中，请 {remain} 秒后再试")
                return
            self._last_trigger[origin] = now

        picked = await self.manager.draw(group.name)
        if not picked:
            yield event.plain_result(
                f"组别 {group.name} 里还没有图片，"
                f"先用「表情 加 {group.name}」或 WebUI 上传"
            )
            return

        logger.info("[astrbot_plugin_randommeme] picked %s for %s", picked, group.name)
        chain = self._build_image_chain(
            picked, event=event if self._reply_mode() else None
        )
        if chain is not None:
            yield event.chain_result(chain)
        else:
            yield event.plain_result(f"图片路径不合法: {picked}")

    async def _try_consume_upload_wait(self, event: AstrMessageEvent):
        key = self._user_key(event)
        state = self._upload_wait.get(key)
        if not state:
            return
        if time.time() > float(state.get("expire", 0)):
            self._upload_wait.pop(key, None)
            return
        if not collect_image_components(event):
            return

        group_name = str(state.get("group") or "")
        self._upload_wait.pop(key, None)
        async for result in self._do_add_images(event, group_name):
            yield result

    # --------------------------------------------------------- 指令组：表情

    @filter.command_group("表情")
    def meme_cmd(self):
        """随机表情包指令组"""
        pass

    @meme_cmd.command("帮助", alias={"help", "?"})
    async def cmd_help(self, event: AstrMessageEvent):
        yield event.plain_result(HELP_TEXT)

    @meme_cmd.command("列表", alias={"list", "ls"})
    async def cmd_list(self, event: AstrMessageEvent):
        groups = self.manager.list_groups()
        if not groups:
            yield event.plain_result(
                "还没有任何组别。用「表情 新 <名称>」创建，或去 WebUI。"
            )
            return
        lines = ["组别列表:"]
        for g in groups:
            count = self.manager.image_count(g.name)
            alias_text = ", ".join(g.aliases) if g.aliases else "-"
            status = "启用" if g.enabled else "禁用"
            wake = "(需唤醒)" if g.require_wake else ""
            lines.append(
                f"- {g.name}{wake} [{status}] 图:{count} | 别名:{alias_text}"
            )
        yield event.plain_result("\n".join(lines))

    @meme_cmd.command("加", alias={"add"})
    async def cmd_add(self, event: AstrMessageEvent, group: str = ""):
        if not self._manage_allowed(event):
            yield event.plain_result(self._deny_manage_msg())
            return
        name = (group or "").strip()
        if not name:
            yield event.plain_result(
                "用法：表情 加 <组别>（可同条带图，或回复一张图，或发完再丢图）"
            )
            return
        if not self.manager.get_group(name):
            yield event.plain_result(
                f"未找到组别：{name}。先用「表情 新 {name}」创建。"
            )
            return

        uploads = await extract_image_uploads(event)
        if uploads:
            async for result in self._do_add_images(event, name, uploads=uploads):
                yield result
            return

        key = self._user_key(event)
        self._upload_wait[key] = {
            "group": name,
            "expire": time.time() + _UPLOAD_WAIT_SECONDS,
        }
        yield event.plain_result(
            f"请在 {_UPLOAD_WAIT_SECONDS} 秒内发送要加入「{name}」的图片（可多张）。"
        )

    def _resolve_cmd_tail(self, event: AstrMessageEvent, rest, *subcommands: str) -> str:
        """合并 GreedyStr 与原文截取，取更完整的参数串。

        AstrBot 若未识别 GreedyStr（例如 future annotations 把注解变成字符串），
        只会把第一个词赋给 rest，后面的别名会丢。此时必须从 message_str 兜底。
        """
        from_rest = str(rest or "").strip()
        from_msg = ""
        for sub in subcommands:
            from_msg = _message_tail_after_subcommand(event, sub)
            if from_msg:
                break
        if len(_split_tokens(from_msg)) > len(_split_tokens(from_rest)):
            return from_msg
        return from_rest or from_msg

    @meme_cmd.command("新", alias={"new", "新建"})
    async def cmd_new(self, event: AstrMessageEvent, rest: GreedyStr = ""):
        if not self._manage_allowed(event):
            yield event.plain_result(self._deny_manage_msg())
            return
        tokens = _split_tokens(self._resolve_cmd_tail(event, rest, "新", "new", "新建"))
        if not tokens:
            yield event.plain_result("用法：表情 新 <名称> [别名1 别名2 …]")
            return
        group_name = tokens[0]
        aliases = tokens[1:]
        try:
            g = await self.manager.create_group(group_name, aliases=aliases)
        except ValueError as exc:
            yield event.plain_result(str(exc))
            return
        alias_text = ", ".join(g.aliases) if g.aliases else "无"
        yield event.plain_result(f"已创建组别「{g.name}」，别名：{alias_text}")

    @meme_cmd.command("别名", alias={"alias"})
    async def cmd_aliases(self, event: AstrMessageEvent, rest: GreedyStr = ""):
        if not self._manage_allowed(event):
            yield event.plain_result(self._deny_manage_msg())
            return
        tokens = _split_tokens(self._resolve_cmd_tail(event, rest, "别名", "alias"))
        if len(tokens) < 2:
            yield event.plain_result(
                "用法：表情 别名 <组别> <别名1> [别名2 …]（覆盖该组别全部别名）"
            )
            return
        group_name = tokens[0]
        aliases = tokens[1:]
        if not self.manager.get_group(group_name):
            yield event.plain_result(f"未找到组别：{group_name}")
            return
        try:
            g = await self.manager.update_group(group_name, aliases=aliases)
        except ValueError as exc:
            yield event.plain_result(str(exc))
            return
        alias_text = ", ".join(g.aliases) if g.aliases else "（已清空）"
        yield event.plain_result(f"「{g.name}」别名已更新：{alias_text}")

    # --------------------------------------------------------- 旧指令兼容（帮助不再主推）

    @filter.command("随机meme", alias={"随机表情", "包帮助"})
    async def cmd_help_legacy(self, event: AstrMessageEvent):
        yield event.plain_result(HELP_TEXT)

    @filter.command("随机meme列表", alias={"meme列表"})
    async def cmd_list_legacy(self, event: AstrMessageEvent):
        async for r in self.cmd_list(event):
            yield r

    @filter.command("随机meme详情", alias={"meme详情", "表情详情"})
    async def cmd_group_detail(self, event: AstrMessageEvent, name: str = ""):
        if not name:
            yield event.plain_result(
                "用法：随机meme详情 <组别名>（也可直接 表情 列表）"
            )
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
    async def cmd_reset_group(self, event: AstrMessageEvent, name: str = ""):
        if not self._manage_allowed(event):
            yield event.plain_result(self._deny_manage_msg())
            return
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
    async def cmd_disable_group(self, event: AstrMessageEvent, name: str = ""):
        if not self._manage_allowed(event):
            yield event.plain_result(self._deny_manage_msg())
            return
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
    async def cmd_enable_group(self, event: AstrMessageEvent, name: str = ""):
        if not self._manage_allowed(event):
            yield event.plain_result(self._deny_manage_msg())
            return
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

    async def _do_add_images(
        self,
        event: AstrMessageEvent,
        group_name: str,
        uploads=None,
    ):
        if uploads is None:
            uploads = await extract_image_uploads(event)
        if not uploads:
            yield event.plain_result("没有识别到图片，请带图发送或回复一张图片。")
            return
        try:
            stored = await self.manager.add_images(group_name, uploads)
        except ValueError as exc:
            yield event.plain_result(str(exc))
            return
        if not stored:
            yield event.plain_result("没有可保存的图片（扩展名不支持或内容为空）。")
            return
        total = self.manager.image_count(group_name)
        yield event.plain_result(
            f"已添加 {len(stored)} 张到「{group_name}」，当前共 {total} 张。"
        )

    def _is_woken(self, event: AstrMessageEvent, text: str) -> bool:
        extra = str(self.conf.get("extra_prefix") or "")
        if extra and text.startswith(extra):
            return True
        return bool(getattr(event, "is_at_or_wake_command", False))

    def _should_handle(self, event: AstrMessageEvent, text: str) -> bool:
        if self._is_woken(event, text):
            return True
        if not bool(self.conf.get("need_prefix", True)):
            return True
        return False

    def _strip_prefix(self, text: str) -> str:
        extra = str(self.conf.get("extra_prefix") or "")
        if extra and text.startswith(extra):
            return text[len(extra) :].strip()
        return text

    def _build_image_chain(self, path, event=None):
        if not is_image_filename(path, gif_support=self.manager.gif_support):
            return None
        chain = [CompImage.fromFileSystem(path)]
        if event is not None:
            msg_id = getattr(event.message_obj, "message_id", "")
            if msg_id:
                chain.insert(0, Reply(id=str(msg_id)))
        return chain
