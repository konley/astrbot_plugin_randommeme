# astrbot_plugin_randommeme · 随机表情包

一个 AstrBot 插件：用户发送关键词（精确匹配，前后空格忽略），从对应"组别"目录中**随机且不重复**地抽取一张图片发送。支持多组别、别名、需唤醒开关、WebUI 管理页，附带批量上传、批量删除、抽取序列重置等管理能力。

> 适配器：`aiocqhttp`、`qq_official`
> GIF：支持（可关闭）
> AstrBot 版本：`>=4.0.0`

---

## 目录

1. [特性](#特性)
2. [安装](#安装)
3. [快速上手](#快速上手)
4. [使用说明](#使用说明)
5. [指令列表](#指令列表)
6. [配置项](#配置项)
7. [WebUI / Plugin Page](#webui--plugin-page)
8. [数据存储](#数据存储)
9. [目录结构](#目录结构)
10. [常见问题](#常见问题)
11. [开发与测试](#开发与测试)
12. [许可](#许可)

---

## 特性

- **精确匹配 + 空格容忍**：发送 `摸鱼` / `  摸鱼  ` 都能命中，前后空格自动忽略，但 **不会** 模糊匹配 `摸鱼一下` 这种部分匹配。
- **多组别独立目录**：每个组别对应一个图片目录，互不干扰。
- **别名**：每个组别可设置多个别名（亦用于精确匹配）。
- **需唤醒开关**：可指定某些组别在 @机器人 或带前缀的情况下才触发，不影响其他组别。
- **随机 + 不重复**：一整轮抽取完之后才洗牌，全局共享抽取池。
- **支持动图**：JPG / PNG / WEBP / BMP / GIF 全开。
- **WebUI 管理**：内置 Plugin Page，含组别 CRUD、批量上传、批量删除、重置抽取序列、统计。
- **指令管理**：`随机meme` 系列命令支持不依赖 WebUI 完成日常管理。
- **数据隔离**：所有持久化数据落在 `data/plugin_data/astrbot_plugin_randommeme/`，与插件源码分离，便于迁移备份。

---

## 安装

1. 将本仓库克隆 / 复制到 AstrBot 的插件目录：

   ```text
   AstrBot/data/addons/plugins/astrbot_plugin_randommeme/
   ```

2. 在 AstrBot WebUI → 插件管理 → 找到 `astrbot_plugin_randommeme`，点击 **启用** 或 **重载**。

3. 加载成功后日志中应出现：

   ```text
   [astrbot_plugin_randommeme] initialized; groups=0
   ```

4. 在 WebUI → 插件 → 随机表情包 → "组别管理" Tab 中点 **新建组别**，上传图片即可使用。

> 💡 如果你的部署目录不是 `data/addons/plugins/`，把上面的路径换成实际 `plugin_store_path`（默认 `data/plugins/` 或 `data/addons/plugins/`，取决于 AstrBot 版本与是否启用 addon 模式）。

---

## 快速上手

### 步骤 1：创建组别

WebUI → 随机表情包 → 组别管理 → 新建组别。填：

| 字段     | 示例              | 说明 |
|----------|-------------------|------|
| 组别名称 | `摸鱼`            | 唯一；发送该值即可触发 |
| 别名     | `摸鱼一下` `moyu` | 多行，每行一个 |
| 需唤醒   | 勾选 / 不勾       | 勾上后必须 @机器人 或带额外前缀才触发 |

### 步骤 2：上传图片

切换到 **图片管理** Tab，选中刚创建的组别：

- 点 **点击或拖拽多张图片到此处**
- 或拖拽一批图片到上传区
- 多选缩略图后点 **批量删除**

### 步骤 3：触发

群里发送：

```text
摸鱼
@机器人 摸鱼一下
moyu
```

机器人会从该组别目录中抽一张图发送。一组别抽完才会洗牌。

---

## 使用说明

### 触发规则

| 场景 | 是否触发 |
|------|----------|
| 发送 `摸鱼` | ✅ 命中 "摸鱼" |
| 发送 `  摸鱼  ` | ✅ 自动 strip |
| 发送 `MOYU` | ✅ 命中别名（大小写不敏感） |
| 发送 `摸鱼一下` 但仅定义了 `摸鱼` 和别名 `moyu` | ❌ 不命中（**无模糊匹配**） |
| 发送 `摸鱼` 但该组别 *需要唤醒*，且没 @机器人 | ⚠️ 提示需要唤醒 |
| 私聊发送 `摸鱼` + `need_prefix=true` 但没 `@机器人` | ⚠️ 不命中（私聊亦受前置规则约束） |

### 抽取规则

- 组别内的每张图在 **一整轮** 内只会被抽到一次。
- 跑完一轮后自动洗牌（重置该组别的 history）。
- 抽取池是 **全局共享** 的：所有群聊、私聊都共用同一个抽取序列，不会因为多群并发导致快速洗牌。
- 删除某张图后，若它仍在 `history` 中，会被自动剔除；不会留下空指针。
- 手动重置抽取序列：
  - WebUI → 随机表情包 → 组别管理 → 顶栏 **重置全部抽取序列**
  - WebUI → 图片管理 → **重置该组抽取序列**
  - 指令：`随机meme重置 <组别>` 或 `随机meme重置`（清空全部）

### 需唤醒开关

某些敏感的组别（比如工作专用）你可以设置 *需唤醒*。也就是说仅当：

1. 消息里有 @机器人（`is_at_or_wake_command` 为真），或
2. 消息以 `extra_prefix` 开头

才会触发。其他消息只会得到一句提示，不会被 LLM 误命中（也不消耗上下文）。

---

## 指令列表

| 指令 | 别名 | 说明 |
|------|------|------|
| `随机meme` | `随机表情`、`包帮助` | 显示使用说明 |
| `随机meme列表` | `meme列表`、`表情列表` | 列出所有组别与图片数 |
| `随机meme详情 <组别>` | `meme详情`、`表情详情` | 查看组别详细信息 |
| `随机meme重置 [组别]` | `meme重置`、`表情重置` | 不带组别=重置全部；带组别=重置该组 |
| `随机meme禁用 <组别>` | `meme禁用`、`禁用表情` | 关闭组别（保留图片） |
| `随机meme启用 <组别>` | `meme启用`、`启用表情` | 恢复组别 |

> 也可以通过 WebUI 完成同等操作。所有指令都是普通消息（受 `need_prefix` 控制），并不会触发 LLM。

---

## 配置项

修改 WebUI → 插件管理 → `随机表情包` → 配置。

| Key | 类型 | 默认 | 说明 |
|-----|------|------|------|
| `need_prefix` | bool | `true` | 是否需要 @机器人 / 唤醒前缀才能触发抽取。关闭后可被任何文本直接触发（**小心与 LLM 误命中**）。 |
| `extra_prefix` | string | 空 | 可选的额外触发前缀，例如 `/`；为空则不启用额外前缀。 |
| `gif_support` | bool | `true` | 是否支持发送 GIF 动图。关闭后 `.gif` 文件会在上传时被忽略。 |
| `send_as_image_component` | bool | `true` | 以 Image 组件发送图片；关闭后改用纯文本提示（仅在调试时建议关闭）。 |

---

## WebUI / Plugin Page

进入路径：**WebUI → 插件 → 随机表情包**。Plugin Page 包含 4 个 Tab：

### 组别管理

- 列出所有组别（名称、别名、图片数、状态、是否需唤醒）。
- 创建组别：唯一性、别名冲突在表单层和后端双向校验。
- 编辑：可改别名、需唤醒、是否启用；组别名称不可改（要改请删除重建）。
- 删除：连图片目录一起删除，二次确认。
- 重置全部抽取序列（仅清空 history，不动图片）。

### 图片管理

- 选择组别 → 显示该组别所有图片缩略图。
- **拖拽 / 点选上传**：支持多文件批量，扩展名白名单（jpg/jpeg/png/webp/bmp/gif）。
- 单张删除 / 多选批量删除。
- 重置该组的抽取序列。
- 数据为空时显示占位符。

### 全局设置

只读展示：组别数、插件名、支持的格式、抽取规则等。
实际配置项请回 AstrBot 插件配置页修改（schema 字段在 `_conf_schema.json`）。

### 统计

- 全局：组别数 / 图片总数 / 本轮累计抽取。
- 逐组别：图片数 / 本轮已抽 / 剩余。**剩余 = 0 表示下次抽取将触发洗牌**。

### Bridge 端点速查

所有 endpoint 与相对路径前缀 `/astrbot_plugin_randommeme`，但通过 bridge 调用时已自动去掉前缀：

| endpoint | 方法 | 说明 |
|----------|------|------|
| `groups` | GET | 列出组别 |
| `groups` | POST | 新建 `{name, aliases[], require_wake}` |
| `groups/<name>` | GET | 单组详情 |
| `groups/<name>/update` | POST | 局部更新 `{aliases?, require_wake?, enabled?}` |
| `groups/<name>/delete` | POST | 删除组别与目录 |
| `groups/<name>/images` | GET | 列图片 |
| `groups/<name>/images` | POST | 上传（multipart `file`） |
| `groups/<name>/images/delete` | POST | 批量删除 `{filenames[]}` |
| `groups/<name>/images/<path:filename>` | GET | 取单张图片（预览用） |
| `groups/<name>/reset` | POST | 重置该组抽取序列 |
| `reset` | POST | 重置所有 |
| `stats` | GET | 统计信息 |

---

## 数据存储

所有持久化数据统一落在 AstrBot 的 plugin_data 目录：

```text
data/plugin_data/astrbot_plugin_randommeme/
├── groups.json                       # 组别定义 + 抽取历史
└── memes/
    ├── 摸鱼/
    │   ├── 001.jpg
    │   └── 002.gif
    ├── 干饭/
    │   └── 001.png
    └── ...
```

### `groups.json` 格式

```json
{
  "groups": [
    {
      "name": "摸鱼",
      "aliases": ["摸鱼一下", "moyu"],
      "require_wake": false,
      "enabled": true,
      "created_at": 1718000000
    }
  ],
  "history": {
    "摸鱼": ["001.jpg", "002.gif"]
  }
}
```

- 字段含义与 Plugin Page 表单一一对应。
- `history` 会在抽取序列自然走完或手动重置时被清空。
- 文件使用 UTF-8（无 BOM）+ LF 换行 + 原子替换（`*.tmp` + `os.replace`），写入中途被中断不会损坏原文件。

---

## 目录结构

```text
astrbot_plugin_randommeme/
├── __init__.py
├── metadata.yaml              # 插件元数据
├── _conf_schema.json          # WebUI 配置面板的 schema
├── requirements.txt           # 无三方依赖
├── main.py                    # AstrBot 入口（消息处理 + 指令）
├── core/
│   ├── __init__.py
│   ├── group.py               # Group dataclass + state 序列化
│   ├── manager.py             # MemeManager: 组别/图片/抽取池/匹配
│   ├── storage.py             # data 目录 / 文件名 / 路径校验
│   └── api.py                 # Web API handlers（plugin-page 后端）
├── pages/
│   └── manager/               # Plugin Page: 单页综合管理
│       ├── index.html
│       ├── style.css
│       └── app.js
└── tests/
    ├── conftest.py            # astrbot stub + fixture
    ├── test_smoke.py          # 模块导入 / schema / page layout
    └── test_plugin_behavior.py# MemeManager 行为测试
```

---

## 常见问题

### Q: 触发时提示"触发 摸鱼 需要 @机器人 或唤醒前缀"

答：检查这个组别是否勾了 *需要唤醒*。要关闭请：

- WebUI → 编辑该组别 → 取消 **需要 @机器人 / 唤醒前缀**
- 或 `随机meme禁用` + `随机meme启用` 重写也行（不会清空图片）

### Q: 上传成功后图片没出现？

答：先在 **图片管理** Tab 刷新下拉框（切到别的组别再切回来）。如果还看不到：

- 检查 `gif_support` 是否关闭且你上传的是 `.gif`。
- 检查文件实际是否落地到 `data/plugin_data/astrbot_plugin_randommeme/memes/<组别>/`。
- 看 AstrBot 主日志是否有 `add_images` 异常。

### Q: 抽取一直重复，怎么强制洗牌？

答：  
WebUI → **重置该组抽取序列** 或 **重置全部抽取序列**  
指令：`随机meme重置 <组别名>`

### Q: 不要 `@机器人` 也能直接触发关键词吗？

答：默认需要（`need_prefix=true`）。你可以在 AstrBot 插件配置页把它改成 `false`，**但请确认**：如果机器人同时启用了 LLM，所有文本都会先经过 LLM，本插件的抽取会在 LLM 之后再做，并且只有在 LLM 流程未中断的分支上发生。多数情况下你只想在某些组别关闭，可以勾 *需要唤醒* 作为反向用法。

### Q: WebUI 中图片缩略图加载失败？

答：Plugin Page 通过 `GET /groups/<name>/images/<path:filename>` 取得真实文件。  
可能原因：

- 上传文件扩展名不在白名单内 → 检查日志中 `add_images` 报错。
- dashboard 与浏览器 Cookie 异常 → 重新登录 WebUI 后刷新 iframe。
- 某些代理 / 反代把 `/api/plug/` 路由拦截了。

### Q: 怎么备份 / 迁移？

答：直接拷贝 `data/plugin_data/astrbot_plugin_randommeme/` 整个目录。Group 定义在 `groups.json`，图片在 `memes/` 下。

---

## 开发与测试

### 本地直接开发

```bash
# 在项目根目录安装 AstrBot 开发依赖（请参考 AstrBot 文档）
# 本项目本身仅依赖 stdlib，不需要 requirements.txt 安装任何东西。

# 跑测试（pytest + pytest-asyncio + pyyaml）
pytest -q
```

> **测试用的 `astrbot` stub** 在 `tests/conftest.py` 里手工注入，所以即使本地没有装 `astrbot` 包也能跑。

### 代码风格

- 遵循 AstrBot 官方插件规范（metadata.yaml + _conf_schema.json）。
- ruff 推荐使用：
  ```bash
  ruff format .
  ruff check .
  ```
- Python ≥ 3.10；类型注解使用 PEP 604 / 585 风格（`list[str] | None`）。
- KISS 原则：能不抽象就别抽象，没有 3+ 处复用就不抽函数。

### 调试建议

- 编辑完代码 → WebUI → 插件管理 → **重载**。比重启快很多。
- 改 `_conf_schema.json` → 也只需重载。
- 改 `pages/` 子目录 → 重载 + 刷新 iframe。
- 排查 "插件加载失败" → AstrBot 主日志搜 `astrbot_plugin_randommeme`。

### 发布

1. 在 `metadata.yaml` 中更新 `version`（follow semver）。
2. 跑 `pytest -q` 与 `ruff format . && ruff check .`。
3. 推送到 Git / 插件市场。

---

## 许可

MIT
