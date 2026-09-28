# GitHub 开发流程

本文档记录 Module Agent 的日常开发流程。原则是：一个 Issue 对应一个功能分支和
一个 Pull Request，代码通过测试与审查后才能进入 `main`。

## 1. 创建 Issue

在 GitHub 的 `Issues → New issue` 中描述问题，至少写清楚：

- 当前行为；
- 期望行为；
- 验收标准；
- 可能涉及的文件。

记下 Issue 编号，例如 `#1`。后面的分支名和 PR 都使用这个编号关联需求。

## 2. 从最新 main 创建分支

```bash
git switch main
git pull --ff-only
git switch -c fix/1-short-description
```

分支名前缀建议：

- `fix/`：修复缺陷；
- `feat/`：增加功能；
- `docs/`：只修改文档；
- `refactor/`：重构但不改变外部行为；
- `test/`：补充或改进测试。

确认当前分支和工作区状态：

```bash
git branch --show-current
git status
```

不要直接在 `main` 上开发功能。

## 3. 先用测试复现问题

先添加一个能够稳定复现问题的测试，然后运行对应测试文件：

```bash
uv run pytest path/to/test_file.py -q
```

此时新测试应该因为目标问题而失败，而不是因为导入、语法或测试环境错误而失败。
这一步称为 TDD 的“红灯”阶段。

## 4. 实现最小修复

只修改解决当前 Issue 所需的代码，不顺便混入无关重构。完成后重新运行目标测试：

```bash
uv run pytest path/to/test_file.py -q
```

目标测试通过后即进入“绿灯”阶段。

## 5. 提交前检查

检查改动内容和空白字符：

```bash
git diff
git diff --check
git status --short
```

运行目标测试与全量测试：

```bash
uv run pytest path/to/test_file.py -q
uv run pytest -q
```

涉及数据库模型或迁移时额外运行：

```bash
uv run alembic check
```

涉及 Docker Compose 时额外运行：

```bash
docker compose config --quiet
```

## 6. 创建提交

只暂存本次 Issue 涉及的文件：

```bash
git add path/to/changed_file.py path/to/test_file.py
git diff --cached --stat
git diff --cached
```

确认无误后提交：

```bash
git commit -m "fix: short description"
```

常用提交类型：

- `fix:`：修复问题；
- `feat:`：新增功能；
- `test:`：测试修改；
- `docs:`：文档修改；
- `refactor:`：内部重构；
- `chore:`：工程配置或维护工作。

提交后检查：

```bash
git status
git log -1 --oneline
```

## 7. 推送功能分支

首次推送需要建立远程跟踪关系：

```bash
git push -u origin fix/1-short-description
```

以后在同一分支继续修改时只需：

```bash
git push
```

## 8. 创建 Pull Request

可以在 GitHub 网页创建，也可以使用 GitHub CLI：

```bash
gh pr create \
  --base main \
  --head fix/1-short-description \
  --title "fix: short description" \
  --body "Describe the change and its tests.

Closes #1"
```

其中：

- `--base main` 表示目标分支；
- `--head` 表示包含改动的功能分支；
- `Closes #1` 会在 PR 合并后自动关闭对应 Issue。

查看 PR：

```bash
gh pr view --web
gh pr checks
gh pr diff
```

## 9. 根据 Review 修改

直接在原功能分支修改，不需要重新创建 PR：

```bash
git add path/to/changed_file.py
git commit -m "style: address review feedback"
git push
```

推送后，原 PR 会自动更新并重新运行 CI。

## 10. 合并 PR

确认以下条件均满足：

- PR 的 base 和 head 正确；
- Review 意见已经处理；
- CI 全部通过；
- PR 可以合并；
- PR 正文包含正确的 Issue 关闭语句。

推荐使用 Squash Merge，让 `main` 上每个 PR 只保留一个完整提交：

```bash
gh pr merge <PR编号> --squash --delete-branch
```

例如：

```bash
gh pr merge 4 --squash --delete-branch
```

## 11. 合并后同步本地仓库

```bash
git switch main
git pull --ff-only
git status
git log -1 --oneline
```

如果 `--delete-branch` 没有删除本地功能分支，并且确认 PR 已经合并，可以删除它：

```bash
git branch -d fix/1-short-description
```

若使用 Squash Merge，Git 可能认为原分支提交没有直接进入 `main`，从而拒绝 `-d`。
确认分支内容已通过 PR 合并后，才可以使用：

```bash
git branch -D fix/1-short-description
```

## 12. 常用查询命令

```bash
# 当前分支和文件状态
git status --short --branch

# 本地分支及其远程跟踪关系
git branch -vv

# 最近的提交
git log --oneline --decorate -10

# 查看 Issue
gh issue view <Issue编号>

# 查看 PR 状态
gh pr view <PR编号>

# 查看 PR 的 CI
gh pr checks <PR编号>

# 查看 PR 改动
gh pr diff <PR编号>
```

## 完整流程速查

```text
Issue
  → 更新 main
  → 创建功能分支
  → 编写失败测试
  → 实现修复
  → 目标测试和全量测试
  → Commit
  → Push
  → Pull Request
  → Review
  → CI
  → Squash Merge
  → Issue 自动关闭
  → 同步本地 main
```
