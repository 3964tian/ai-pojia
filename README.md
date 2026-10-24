# AI破甲 · ai-pojia

左手的 DEMO 实战 Skill：把自己编写或获授权的测试程序交给 AI，完成分析、修改和运行验证。

**当前版本：v0.1.0 预览版。** 已提供 Skill、独立安装/卸载工具和插件清单；左手的测试 DEMO 待补充，尚无真实 DEMO 通关成绩或模型对比数据。

## 三步开始

准备一个支持本地 Skills 的 Codex 客户端，以及 Python 3.9 或以上版本。安装器仅使用 Python 标准库；执行实战任务仍需要客户端已有的模型、文件访问和相应分析工具。

```bash
git clone https://github.com/zgx949/ai-pojia.git
cd ai-pojia
python3 tools/manage_skill.py install
```

Windows 可使用 `py -3` 替代 `python3`。本版本安装器的实际验证环境见 [验证记录](docs/validation.md)。

在客户端重新加载 Skills 或开始新会话，然后把自己的测试 DEMO 放进独立工作目录，发送：

> 用 $ai-pojia 分析这个我自己编写的测试 DEMO。先说明它如何工作，再在副本上完成我指定的修改，实际运行验证，并保留原文件和修改记录。

目标是得到可检查的实际产物：原始文件摘要、分析证据、修改后的副本、验证命令、运行结果和可恢复记录。缺少模型、工具或 DEMO 时会明确说明缺项。

## 安装与卸载

默认安装到 `${CODEX_HOME}/skills/ai-pojia`；未设置 `CODEX_HOME` 时使用 `~/.codex/skills/ai-pojia`。工具支持显式指定 Skills 目录：

```bash
# 预览，不写入文件
python3 tools/manage_skill.py install --dry-run

# 只读检查
python3 tools/manage_skill.py doctor

# 安装到指定的 Skills 目录
python3 tools/manage_skill.py install --skills-dir /absolute/path/to/skills

# 卸载并归档当前受管版本
python3 tools/manage_skill.py uninstall
```

安装器只管理自己的 Skill 目录及同级备份目录。更新和卸载前会检查文件摘要；发现手动改动、未知文件或损坏的管理记录时，会停止操作并保留现场。历史版本保存在 Skills 目录下的 `.ai-pojia-backups/`。

本版本以以上 Python 安装方式为准。[plugin.json](plugin.json) 提供插件打包入口，尚未提交或上架公共插件目录。

## DEMO 实战

左手后续会提供独立测试 DEMO。当前 [demos/](demos/) 仅说明接入要求，没有测试程序，也没有预置答案。提交自己的程序前，参考 [DEMO 接入说明](skills/ai-pojia/references/demo-contract.md)。

每次实战都以用户指定的目标为准，在副本上操作，并将“模型拒答、工具缺失、分析失败、运行失败、验证通过”分开记录。Skill 提供工作流；它本身不会增加模型或逆向工具的权限，也不保证消除模型拒答。

## 来源与修改

安装工具复用了 [MDX-Tom/gpt-instruct](https://github.com/MDX-Tom/gpt-instruct) 的原子写入实现，并借鉴其备份、状态记录、摘要校验及回滚方式。

ai-pojia 将部署目标改成独立 Skill 目录，加入完整目录校验、更新归档与卸载归档。当前包未包含上游通用越狱提示词、历史提示词 ZIP 或其模型评测结果。

固定来源版本、修改范围和版权见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。感谢原作者 li lingbo、yynxxxxx 及上游维护者。

## 本地验证与打包

```bash
python3 -m unittest discover -s tests -v
python3 tools/package_release.py
```

验证分为安装器测试、Skill 结构检查和真实 DEMO 实战。前两项通过不代表第三项完成；具体范围见 [验证记录](docs/validation.md)。

项目原创内容使用 MIT；上游版权声明及 MIT 全文保留在 [third_party/gpt-instruct/LICENSE](third_party/gpt-instruct/LICENSE)。
