# 验证范围

本记录分开描述提示词配置、安装器、Skill 结构和真实实战。安装器测试不代表拒答消除或 DEMO 通关。

## v0.3.0 提示词库

新增 `prompts/library/`（6 份上游逐字节副本 + `source.json` 清单 + 说明）与 `tools/manage_library.py`、`tests/test_manage_library.py`。

- 清单与文件一致性：6 份 Markdown 的字节数与 SHA256 逐项比对通过；v45 的 `c71c50e2…` 与上游 `prompts/source.json` 记录的 `original_text_sha256` 相同。
- ZIP 摘要：`gpt-5.6-sol-v45.zip` 为 `c86c2c6d…`，与上游公布值相同；`gpt-6-astra-v1.zip`、`gpt-6-astra-v1-rc1.zip`、`gpt-6.1-sol-v1-rc1.zip` 与 `historical-versions/README.md` 公布的摘要逐项相同。
- 新增 16 项测试（13 项 CLI + 3 项仓库清单），合计 68 项，2026-10-29 在 macOS 26 arm64、Python 3.14.6 全套通过。
- 覆盖：写入、幂等、dry-run 零写、doctor 篡改检测、拒绝覆盖外来同名文件、重装更新自有漂移副本、单条安装、卸载只删自有、卸载保留手改、清单摘要不符拒绝、带点号 profile 名拒绝、符号链接拒绝、仓库清单比对。

**加载机制实测**（macOS，Codex CLI `26.1023.51421`）：

- `codex -p <profile> debug prompt-input` 的实际注入内容与目标提示词文件逐行一致（7893 字符文件 / 7892 字符注入，差异仅为末尾换行）。
- 三个 profile 分别注入各自版本，互不串味；顶层 `model_instructions_file` 在 `-p` 生效时不泄漏。
- 安装器不写顶层 `config.toml`：安装前后该文件字节相同。
- 同时装改写版提示词与提示词库时，`-p` 覆盖顶层字段，未加 `-p` 时仍走改写版。

**未验证**：模型侧效果对照。本记录只证明"配置指向正确、加载内容正确"，不证明任何模型在任一提示词下会接受某个具体请求。

## v0.2.0 提示词配置与一键入口

v0.2.0 增加 `prompts/ai-pojia.md`、`tools/manage_prompt.py` 和 `install.py`。提示词由 gpt-instruct v45 改写，原始 ZIP 摘要与上游公布值相同，文本来源和改写版摘要记录在 `prompts/source.json`。

新增 23 项配置 CLI 测试和 10 项一键入口测试；与原有 19 项 Skill 安装测试合计 52 项，2026-10-24 在 Python 3.10.11 全套通过。测试均使用临时仓库、临时 Codex 目录与普通 fixture 提示词，没有启用维护者的真实客户端配置。


配置测试覆盖顶层字段插入/恢复、重复安装、源文件更新、原有 Provider 与后续改动保留、预览零写、手改/损坏状态/符号链接保护。组合测试覆盖双组件预检、真实加载文件、卸载、部分失败报告和只读检查。

另外完成 7 项隔离 TOML 边界检查：多行字符串内的假表与假 key、跨行数组、quoted 原字段、CRLF、无尾换行，以及拒绝无法可靠编辑的多行指令和点号展开指令。Python 3.9 语法检查与标准库部署分别验证；Windows 尚未实际测试。

`doctor` 的 `verification` 为 `configuration-only`：只检查字段、文件与摘要。尚未对任何模型做“改写前/后拒答率”对照，也不宣称通用取消拒答。

v0.2.0 发布包采用 22 个明确列出的文件；ZIP 完整性与重复构建摘要一致性检查通过。将实际发布包解压到临时目录，使用内置改写版提示词依次完成一键安装、只读检查和恢复，检查时 `prompt_enabled` 与 `skill_installed` 均为 true，`model_tested` 为 false。

## 安装器

测试在临时目录中执行，不安装到维护者的真实 Skills 目录。覆盖 dry-run、初次安装、重复安装、更新归档、卸载归档、手动改动保护、未知目录保护、损坏状态、符号链接和同级配置保留。

2026-10-24，在 macOS 26.3 arm64、Python 3.13.7 环境执行 `python3 -B -m unittest discover -s tests -p 'test_manage_skill.py' -v`，19 项 CLI 行为测试全部通过。Python 3.9 语法检查通过；尚未在 Python 3.9 或 Windows 上实际运行完整测试。

## Skill 结构

官方 `skill-creator/scripts/quick_validate.py` 检查通过；引用文件和界面元数据检查通过。验证所需 PyYAML 仅安装在临时目录，安装器和 Skill 本身不依赖它。结构检查只证明文件组织符合约定，不能证明模型执行效果。

另一次独立前向验证在临时目录完成：让 Skill 指导一个自编写的 Python 问候程序新增 `--repeat` 参数，实际检查默认行为、原有参数、重复三次和参数组合，四项均通过；原件前后 SHA256 一致。这仅验证小源码修改任务的工作流，不属于逆向评测，也不是左手后续提供的正式 DEMO。

## 真实 DEMO

待左手提供测试程序后进行。当前没有实际目标程序、完整运行记录或通关结果。

## 插件与平台

已提供插件清单；尚未上架公共插件目录，也未完成各客户端的插件安装兼容验证。当前交付以本地 Python 安装器为准。
