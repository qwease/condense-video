# 实施工作流程 - Condense Video Python Backend

**版本**: 1.0
**创建日期**: 2026-02-27

## 概述

本文档定义了在 Condense Video Python Backend 项目中必须遵循的实施工作流程。所有开发人员必须严格遵守此流程。

---

## 1. 开发前准备

### 1.1 文档优先原则

**规则**: 在编写任何代码之前，必须先阅读相关设计文档。

```
设计文档优先级:
1. docs/design/implementation-plan.md - 总体实施计划
2. docs/design/architecture.md - 架构设计
3. docs/design/components.md - 组件设计
4. docs/design/data-models.md - 数据模型
5. docs/design/api-design.md - API 设计
6. docs/design/config.md - 配置管理
7. docs/design/error-handling.md - 错误处理
8. docs/design/deployment.md - 部署配置
```

### 1.2 工作区创建

**规则**: 每个功能实施必须在独立的 Git Worktree 中进行。

```bash
# 创建工作区
git worktree add ../condense-video-feature-<feature-name> -b feature/<feature-name>
cd ../condense-video-feature-<feature-name>
```

---

## 2. 编码流程

### 2.1 编码前检查清单

在开始编写代码之前：

- [ ] 已阅读相关设计文档
- [ ] 已阅读相关规则文件 (`规则/` 目录)
- [ ] 已查看原有 JS 实现作为参考
- [ ] 已创建 TodoList 跟踪任务

### 2.2 编码规范

1. **完整性要求**: 所有功能点必须完整实现，简略带过不被允许
2. **不确定处理**: 不确定的实现方式必须使用 `AskUserQuestion` 获取更多信息
3. **文档参考**: 具体细节不确定时参考原 JS 设计 (`scripts/` 目录)

### 2.3 编码后验证

**规则**: 编写完成后，必须查阅相关文档以确定是否已达成目标。

- [ ] 对照设计文档验证实现
- [ ] 验证数据模型符合定义
- [ ] 验证 API 接口符合规范
- [ ] 验证错误处理符合要求

---

## 3. 任务跟踪

### 3.1 TodoList 创建

**规则**: 完成每一个功能点时，需要创建单独的 TodoList 来跟踪。

```python
# 功能点示例: 配置管理实现
TodoWrite({
    "todos": [
        {"content": "创建 core/config.py 文件", "status": "pending", "activeForm": "创建配置文件"},
        {"content": "实现 AppConfig 类", "status": "pending", "activeForm": "实现配置类"},
        {"content": "实现环境变量加载", "status": "pending", "activeForm": "实现环境变量加载"},
        {"content": "编写配置测试", "status": "pending", "activeForm": "编写测试"},
        {"content": "验证 .env 文件配置", "status": "pending", "activeForm": "验证配置"}
    ]
})
```

### 3.2 完成标准

**规则**: 仅当完成所有 sub-todo 后，一个功能点才算完成。

---

## 4. 文档要求

### 4.1 决策记录

**规则**: 任何做出的决定、设计和备注，必须在相关文档中写明：

1. **来源**: 为什么需要这个决定
2. **内容**: 决定的具体内容
3. **实施**: 如何实施
4. **解决方案**: 最终的解决方案

记录位置: `docs/decisions/` 目录

```markdown
# 决策记录: <决策标题>

**日期**: YYYY-MM-DD
**相关人员**: <开发者>

## 背景
<为什么需要这个决定>

## 决策内容
<决定的具体内容>

## 实施方案
<如何实施>

## 最终方案
<最终采用的解决方案>
```

### 4.2 状态记录

**规则**: 完成一个功能点时，必须实时记录当前状态至文件。

记录位置: `docs/progress/` 目录

```markdown
# 进度记录: <功能名称>

**日期**: YYYY-MM-DD
**状态**: 进行中 / 已完成 / 已阻塞

## 已完成
- [x] <已完成的子任务>

## 进行中
- [ ] <当前正在进行的任务>

## 待完成
- [ ] <待完成的任务>

## 问题
<遇到的问题和解决方案>
```

---

## 5. 状态汇报格式

**规则**: 每次开始输出前，必须显式告诉用户以下信息：

```
---
## 当前状态

**阶段**: <当前阶段名称>
**进度**: <百分比>

### 已完成
- <已完成的任务>

### 进行中
- <当前正在做的任务>

### 待完成
- <待完成的任务>

### 计划
<计划如何完成当前任务>

### 文档更新
<将信息写入什么文档>

### 需要用户信息
<是否需要用户的更多信息 (是/否，如需要请说明具体问题)>
---
```

---

## 6. 实施顺序

根据 `docs/design/implementation-plan.md`，按以下优先级实施：

### P0 (核心功能)
1. 配置管理
2. DashScope 服务客户端
3. Redis 客户端
4. Celery 配置
5. ASR 任务
6. OCR 任务
7. 内容分类任务
8. 工作流编排
9. API 基础路由

### P1 (重要功能)
10. 章节切分任务
11. TTS 任务
12. 视频剪辑任务
13. WebSocket 进度推送
14. 存储抽象层

### P2 (增强功能)
15. 断点续传
16. 任务取消
17. 日志查询
18. 监控指标
19. MinIO 存储

---

## 7. 验证标准

### 7.1 功能验证

每个功能完成后，必须验证：

- [ ] 功能符合设计文档描述
- [ ] 代码通过类型检查 (mypy)
- [ ] 代码通过 linting (ruff/black)
- [ ] 单元测试覆盖率 >= 80%
- [ ] 集成测试通过

### 7.2 验收标准

参考 `docs/design/implementation-plan.md` 第四部分：

#### 功能验收
- [ ] 能够上传/指定视频进行处理
- [ ] ASR 转录正常工作
- [ ] OCR 识别正常工作
- [ ] 内容分类准确
- [ ] 生成浓缩视频
- [ ] API 响应正常
- [ ] WebSocket 实时推送进度

#### 性能验收
- [ ] 并行处理 ASR 和 OCR，时间减少 >30%
- [ ] 支持至少 2 个 Worker 并发
- [ ] 任务状态查询延迟 <100ms

#### 稳定性验收
- [ ] 任务失败自动重试
- [ ] Worker 崩溃后任务恢复
- [ ] 服务重启后任务状态保留

---

## 8. 依赖管理

### 8.1 依赖文件结构

```
requirements/
├── base.txt      # 基础依赖
├── api.txt       # API 服务依赖
└── worker.txt    # Worker 依赖
```

### 8.2 添加新依赖

1. 添加到对应的 requirements/*.txt 文件
2. 在 `docs/decisions/` 中记录决策
3. 更新 `docs/design/deployment.md` 如果需要

---

## 9. 测试要求

### 9.1 测试类型

1. **单元测试**: 测试单个函数/类
2. **集成测试**: 测试组件交互
3. **E2E 测试**: 测试完整工作流

### 9.2 测试位置

```
tests/
├── unit/         # 单元测试
├── integration/  # 集成测试
└── e2e/          # E2E 测试
```

---

## 10. 提交规范

### 10.1 Commit Message 格式

```
<type>: <description>

<optional body>

<optional footer>
```

Types: feat, fix, refactor, docs, test, chore, perf, ci

### 10.2 提交前检查

- [ ] 代码通过所有测试
- [ ] 新增功能有对应测试
- [ ] 文档已更新
- [ ] 决策已记录

---

## 11. 问题处理

### 11.1 遇到不确定情况

使用 `AskUserQuestion` 获取更多信息，不要自行猜测。

### 11.2 遇到阻塞问题

1. 记录到 `docs/progress/` 文件
2. 标记状态为 "已阻塞"
3. 描述问题和可能的解决方案
4. 等待指示

---

## 12. 参考资料位置

| 类型 | 位置 | 用途 |
|------|------|------|
| 设计文档 | `docs/design/` | 架构和设计参考 |
| 原始规则 | `规则/` | 业务逻辑规则 |
| 原始脚本 | `scripts/` | 实现参考 |
| Codemaps | `codemaps/` | 代码结构参考 |
| 决策记录 | `docs/decisions/` | 设计决策 |
| 进度记录 | `docs/progress/` | 实施进度 |

---

## 附录: 快速参考

### 查看当前进度
```bash
cat docs/progress/summary.md
```

### 查看所有决策
```bash
ls -la docs/decisions/
```

### 查看设计文档
```bash
ls -la docs/design/
```

### 运行测试
```bash
pytest tests/ -v --cov=. --cov-report=html
```

### 类型检查
```bash
mypy .
```

### 代码格式化
```bash
black .
ruff check . --fix
```
