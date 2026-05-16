# Coding Agent 工具落地实施计划

> 基于 `articles/` 目录文章分析结果制定
> 版本：v1.0
> 日期：2026-05-16

---

## 一、计划概述

### 1.1 目标

推动 Claude Code、Codex、Trae 等现有 Coding Agent 工具在研发流程中的工程化落地，通过 Harness Engineering 方法论，建立可验证、可治理、可分层的 AI 辅助研发体系。

### 1.2 范围

- **聚焦**：使用现有 Agent 工具，不开发新 Agent 系统
- **基础设施**：GitLab（代码管理，无 CI/CD）、禅道（Bug 管理，无项目自动化）
- **覆盖**：工作流设计、边界管理、安全保障、基础设施优化、实施路线

### 1.3 核心原则

1. **配置即代码**：将 `CLAUDE.md`、Skills、Rules、Hooks 沉淀为仓库级工程资产
2. **验证先行**：Agent 输出必须经过测试、Lint、类型检查等确定性验证
3. **上下文分层**：按任务复杂度匹配不同工作流模式，避免过度编排
4. **人机协作**：Agent 负责执行，人负责判断、验收和关键决策

---

## 二、工作流落地实施

### 2.1 研发工作流设计

基于文章分析，推荐采用 **三层工作流模型**：

#### 第一层：任务准入（Definition of Ready）

**目标**：防止 Agent 在信息不全时盲目执行

| 检查项 | 说明 |
|--------|------|
| 背景是否清晰 | 需求来源、业务场景、用户价值 |
| 期望行为是否明确 | 功能预期、验收标准 |
| 当前行为是否描述 | 现有问题或空白 |
| 复现步骤是否完整 | 测试验证路径 |
| 影响范围是否界定 | 涉及模块、接口、数据库 |
| 完成标准是否可验证 | 测试通过、Lint 通过、Review 通过 |

**Agent 辅助动作**：
- 读取 Issue/需求描述，生成分诊报告
- 识别缺失信息，输出补充问题清单
- 评估任务复杂度（简单/中等/复杂）

#### 第二层：执行通道选择

按任务复杂度匹配执行模式：

| 复杂度 | 特征 | 执行模式 | 工具 |
|--------|------|----------|------|
| 简单 | 局部修改，边界清晰 | 直接对话模式 | Claude Code / Trae |
| 中等 | 跨模块，需规划 | Plan Mode + 单 Agent | Claude Code Plan Mode |
| 复杂 | 系统级重构，长任务 | Spec 先行 + 编排-子 Agent | Claude Code + Subagent |

**Plan Mode 模板**（可直接复用）：

```markdown
## 目标（1 句话）

## 现状（Agent 能看到什么/看不到什么）

## 约束（必须遵守）
- 技术栈/版本：
- 不能改的接口/行为：
- 性能/安全/合规：

## 验收标准（可验证）
- 通过哪些测试/命令：
- 输出长什么样（示例/路径）：

## 风险点（最担心的 1-3 个点）

请先给出方案对比与最终计划（含步骤与回滚），确认后再改代码。
```

#### 第三层：验证与验收（Definition of Done）

**必须通过的验证关卡**：

1. **本地验证**：`pnpm test` / `cargo test` / 对应测试命令
2. **静态检查**：`pnpm lint` / `pnpm typecheck` / 对应检查命令
3. **代码审查**：人工 Reviewer 审核架构、风险、语义
4. **CI 验证**：GitLab CI 流水线构建与测试（基础设施优化后）

### 2.2 GitLab 与 Agent 工具集成方案

#### 现状分析

- GitLab 仅用于代码管理，未配置 CI/CD
- 缺乏自动化构建、测试、部署流程
- Agent 生成代码后无法自动验证

#### 集成方案

**Phase 1：仓库规则层**

在每个项目仓库根目录放置 `CLAUDE.md`：

```markdown
# 项目目标
- 我们优先保证：正确性 > 可维护性 > 性能

# 代码与风格
- 只改与任务相关的文件，避免大范围重排
- 新增代码必须有对应测试（或解释为什么没有）

# 关键命令（必须用这些验证）
- 单测：pnpm test
- 类型：pnpm typecheck
- 格式化：pnpm format

# 已知坑
- 不要直接改 X：因为线上依赖了 Y 的边界行为
- 任何对外 API 的变更必须同时更新 Z
```

**Phase 2：GitLab CI 基础配置**

配置 `.gitlab-ci.yml`，支持 Agent 生成代码的自动化验证：

```yaml
stages:
  - lint
  - test
  - build

variables:
  NODE_VERSION: "20"

lint:
  stage: lint
  script:
    - npm ci
    - npm run lint
    - npm run typecheck
  only:
    - merge_requests
    - main

test:
  stage: test
  script:
    - npm ci
    - npm run test
  only:
    - merge_requests
    - main

build:
  stage: build
  script:
    - npm ci
    - npm run build
  only:
    - merge_requests
    - main
```

**Phase 3：Agent 辅助 Code Review**

- 在 MR 创建时，触发 Codex/Claude Code 进行自动 Review
- Review 范围：程序 Bug、回归、缺失测试
- 人工 Reviewer 聚焦：架构变更、行为变更、安全策略

**Phase 4：Issue 到 PR 闭环**

```
Issue 创建
  → Agent 分诊（是否 Ready）
  → 人工确认
  → Agent 生成实现计划（Plan Mode）
  → 人工确认计划
  → Agent 创建分支并开发
  → 本地验证（test + lint + typecheck）
  → Agent 创建 MR
  → 自动 Review（Agent）
  → 人工 Review
  → CI 验证
  → 合并
```

### 2.3 禅道系统与 Agent 工具对接方案

#### 现状分析

- 禅道仅用于 Bug 管理
- 缺乏项目管理自动化流程
- Bug 修复与代码变更无自动关联

#### 对接方案

**Phase 1：Bug 分诊自动化**

- Agent 读取禅道 Bug 描述，生成分诊报告
- 输出：Bug 类型（代码缺陷/环境问题/需求误解）、优先级、建议修复模块
- 人工确认后进入修复流程

**Phase 2：Bug 修复闭环**

```
禅道 Bug 创建/分配
  → Agent 读取 Bug 详情 + 关联代码
  → Agent 生成修复计划
  → 人工确认
  → Agent 创建修复分支
  → 本地验证
  → Agent 创建 MR（关联禅道 Bug ID）
  → Review + CI
  → 合并后自动更新禅道状态
```

**Phase 3：禅道状态同步**

通过禅道 API 实现状态自动流转：
- MR 创建 → 禅道 Bug 状态更新为「修复中」
- MR 合并 → 禅道 Bug 状态更新为「已解决」
- CI 失败 → 禅道 Bug 添加备注「验证失败，需重新修复」

---

## 三、边界定义与管理

### 3.1 应用边界

| 场景 | Agent 可自主处理 | 必须人工干预 |
|------|------------------|--------------|
| 代码生成 | 局部功能实现、单元测试、文档注释 | 架构设计、公共 API 变更 |
| 代码审查 | 语法错误、风格问题、明显 Bug | 架构风险、安全漏洞、业务逻辑 |
| Bug 修复 | 明确边界内的局部修复 | 根因涉及多系统、需要方案选择 |
| 重构 | 模式稳定的内部重构 | 跨模块重构、影响兼容性 |
| 发布 | 无 | 所有发布决策 |

### 3.2 使用规范

**必须遵守的规则**：

1. **先规划再动手**：复杂任务必须进入 Plan Mode，生成计划并人工确认
2. **只改相关文件**：禁止顺手重构无关代码
3. **验证必过**：任何代码变更必须通过本地测试和静态检查
4. **Show diff before committing**：提交前展示变更差异
5. **敏感操作需审批**：修改 `.env`、CI 配置、数据库迁移需人工确认

**禁止行为**：

- 未经确认直接合并代码
- 修改生产环境配置
- 删除或修改锁定文件（lockfiles）
- 移除功能标志而不搜索所有调用点

### 3.3 审核机制

**三级审核体系**：

| 级别 | 审核内容 | 执行者 |
|------|----------|--------|
| L1：自动验证 | 测试、Lint、类型检查 | CI / Agent Hooks |
| L2：自动 Review | 程序 Bug、回归、测试覆盖 | Agent（Codex PR Review） |
| L3：人工 Review | 架构、安全、语义、长期维护 | 人工 Reviewer |

### 3.4 角色与 Agent 交互模式

| 角色 | 与 Agent 的交互 | 职责 |
|------|----------------|------|
| 开发工程师 | 使用 Agent 辅助编码、调试 | 定义任务、确认计划、验收结果 |
| 测试工程师 | 使用 Agent 生成测试用例、分析 Bug | 设计测试策略、验证 Agent 输出 |
| 产品经理 | 使用 Agent 整理需求、生成 Spec | 定义需求边界、验收功能 |
| 架构师 | 定义 `CLAUDE.md`、Skills、规则 | 设计系统边界、审核架构变更 |
| 安全工程师 | 审核 Agent 生成的安全相关代码 | 定义安全策略、审计日志 |

---

## 四、安全性保障措施

### 4.1 数据安全风险评估

| 风险点 | 风险等级 | 应对措施 |
|--------|----------|----------|
| 代码泄露给外部模型 | 高 | 使用私有化部署或企业版；禁止上传敏感代码到公共 API |
| 敏感信息（密钥、Token）暴露 | 高 | Agent 默认不可读取 `.env`、CI Secrets；配置 deny 规则 |
| 日志中包含敏感数据 | 中 | 日志脱敏；审计日志分级存储 |
| 模型训练数据回流 | 中 | 使用明确承诺不训练数据的供应商；本地日志留存 |

### 4.2 代码生成安全审查机制

**Hooks 配置示例**：

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit",
        "pattern": "*.rs",
        "hooks": [{
          "type": "command",
          "command": "cargo check 2>&1 | head -30",
          "statusMessage": "Checking Rust..."
        }]
      },
      {
        "matcher": "Edit",
        "pattern": "*.py",
        "hooks": [{
          "type": "command",
          "command": "ruff check $FILE",
          "statusMessage": "Checking Python..."
        }]
      }
    ]
  }
}
```

**安全审查清单**：

- [ ] 是否引入新的依赖？依赖是否可信？
- [ ] 是否涉及网络请求？目标地址是否白名单？
- [ ] 是否处理用户输入？是否有注入风险？
- [ ] 是否涉及权限变更？是否最小权限？
- [ ] 是否包含加密/哈希操作？算法是否合规？

### 4.3 GitLab 权限控制方案

| 权限层级 | Agent 权限 | 控制方式 |
|----------|-----------|----------|
| 读取 | 代码库、Issue、MR | 只读 Token |
| 写入 | 创建分支、提交代码 | 受限 Token，仅特定分支 |
| 执行 | 运行 CI、合并 MR | 需人工审批 |
| 管理 | 修改仓库设置、权限 | 禁止 |

**分支保护策略**：

- `main` / `master`：禁止 Agent 直接推送，必须通过 MR
- `feature/*`：Agent 可创建和推送
- `hotfix/*`：Agent 可创建，合并需人工审批

### 4.4 日志审计系统

**必须记录的审计信息**：

```
- 时间戳
- 操作者（Agent / 用户）
- 操作类型（读/写/执行/审查）
- 目标仓库/分支/文件
- 关联 Issue/Bug ID
- 输入 Token 数 / 输出 Token 数
- 成本估算
- 操作结果（成功/失败）
- 人工审批节点记录
```

**日志存储**：
- 本地日志：保留 90 天
- 审计日志：保留 1 年，不可篡改
- 成本日志：按月汇总，异常报警

---

## 五、基础设施优化

### 5.1 GitLab CI/CD 基础配置

**目标**：建立支持 Agent 生成代码自动验证的 CI 流水线

**基础流水线**：

```yaml
# .gitlab-ci.yml
stages:
  - prepare
  - lint
  - test
  - build
  - security

prepare:
  stage: prepare
  script:
    - npm ci --cache .npm --prefer-offline
  cache:
    key: ${CI_COMMIT_REF_SLUG}
    paths:
      - .npm/
      - node_modules/

lint:
  stage: lint
  script:
    - npm run lint
    - npm run typecheck
  dependencies:
    - prepare

test:
  stage: test
  script:
    - npm run test:coverage
  artifacts:
    reports:
      coverage_report:
        coverage_format: cobertura
        path: coverage/cobertura-coverage.xml
  dependencies:
    - prepare

build:
  stage: build
  script:
    - npm run build
  dependencies:
    - prepare

security:
  stage: security
  script:
    - npm audit --audit-level=moderate
  allow_failure: true
```

**Agent 专用验证 Job**：

```yaml
agent-verify:
  stage: test
  script:
    - echo "Running Agent-specific verification"
    - npm run test:agent  # Agent 生成代码的专项测试
    - npm run lint:agent  # Agent 代码风格检查
  only:
    variables:
      - $AGENT_TRIGGERED == "true"
```

### 5.2 禅道系统自动化改造

**API 集成点**：

1. **Bug 创建同步**：GitLab Issue 标签为 `bug` 时，自动同步到禅道
2. **MR 关联**：MR 描述中包含禅道 Bug ID 时，自动关联
3. **状态流转**：MR 合并后，调用禅道 API 更新 Bug 状态
4. **报告生成**：每周自动生成 Agent 辅助修复 Bug 的统计报告

**自动化脚本示例**：

```python
# zentao_sync.py
import requests

def sync_bug_status(bug_id, status, mr_url):
    """同步禅道 Bug 状态"""
    payload = {
        "bugID": bug_id,
        "status": status,
        "comment": f"关联 MR: {mr_url}"
    }
    response = requests.post(
        f"{ZENTAO_API}/bugs/{bug_id}",
        json=payload,
        headers={"Token": ZENTAO_TOKEN}
    )
    return response.json()
```

### 5.3 基础设施评估与升级建议

| 当前状态 | 缺口 | 建议 |
|----------|------|------|
| GitLab 无 CI/CD | 无法自动验证 Agent 代码 | 优先配置基础 CI 流水线 |
| 禅道无自动化 | Bug 修复闭环依赖人工 | 开发 API 集成脚本 |
| 无 Agent 运行环境 | Agent 在本地运行，不可控 | 评估 Managed Agents 或沙箱环境 |
| 无成本监控 | Agent 使用成本不可见 | 建立 Token 消耗和成本追踪 |
| 无统一规则 | 各项目 Agent 行为不一致 | 推行 `CLAUDE.md` 标准化 |

---

## 六、实施阶段与里程碑

### 6.1 阶段划分

#### Phase 1：工具选型与试点（第 1-2 周）

**目标**：选定工具，建立试点项目

| 里程碑 | 交付物 | 责任人 |
|--------|--------|--------|
| M1.1 | 工具选型报告（Claude Code / Codex / Trae） | 架构师 |
| M1.2 | 试点项目选定（1-2 个活跃仓库） | 研发负责人 |
| M1.3 | 试点项目 `CLAUDE.md` 初版 | 架构师 |

#### Phase 2：流程设计与规则沉淀（第 3-4 周）

**目标**：建立标准化工作流和规则体系

| 里程碑 | 交付物 | 责任人 |
|--------|--------|--------|
| M2.1 | 团队 `CLAUDE.md` 模板 | 架构师 |
| M2.2 | Skills 目录结构规范 | 架构师 |
| M2.3 | Agent 使用规范文档 | 研发负责人 |
| M2.4 | 安全审查 Checklist | 安全工程师 |

#### Phase 3：基础设施配置（第 5-6 周）

**目标**：配置 CI/CD 和自动化集成

| 里程碑 | 交付物 | 责任人 |
|--------|--------|--------|
| M3.1 | GitLab CI 基础流水线配置 | DevOps |
| M3.2 | 禅道 API 集成脚本 | 后端开发 |
| M3.3 | Agent 日志审计系统初版 | DevOps |
| M3.4 | 权限控制策略实施 | 安全工程师 |

#### Phase 4：试点应用（第 7-10 周）

**目标**：在试点项目中验证流程

| 里程碑 | 交付物 | 责任人 |
|--------|--------|--------|
| M4.1 | 试点项目完成 10+ 个 Agent 辅助任务 | 开发团队 |
| M4.2 | 问题清单与流程优化建议 | 研发负责人 |
| M4.3 | 成本与效果基线数据 | 项目经理 |

#### Phase 5：全面推广（第 11-16 周）

**目标**：推广到所有项目，建立持续优化机制

| 里程碑 | 交付物 | 责任人 |
|--------|--------|--------|
| M5.1 | 所有活跃仓库配置 `CLAUDE.md` | 各项目负责人 |
| M5.2 | 团队培训完成（覆盖率 100%） | 研发负责人 |
| M5.3 | 效果评估报告（量化指标） | 项目经理 |
| M5.4 | 持续优化机制建立 | 架构师 |

### 6.2 阶段成果评估标准

| 阶段 | 评估标准 |
|------|----------|
| Phase 1 | 工具选型有明确结论；试点项目团队愿意配合 |
| Phase 2 | 规则文档通过评审；至少 3 人参与评审 |
| Phase 3 | CI 流水线跑通；禅道集成完成联调 |
| Phase 4 | Agent 辅助任务成功率 > 70%；平均返工率 < 30% |
| Phase 5 | Agent 辅助代码占比 > 30%；人均产出提升 > 20% |

---

## 七、风险评估与应对

### 7.1 风险识别

| 风险类型 | 风险描述 | 概率 | 影响 |
|----------|----------|------|------|
| 技术风险 | Agent 生成代码质量不稳定 | 高 | 高 |
| 技术风险 | CI/CD 配置复杂，阻碍落地 | 中 | 中 |
| 流程风险 | 团队成员抵触新工具 | 中 | 高 |
| 流程风险 | 人工 Review 瓶颈未缓解 | 中 | 中 |
| 安全风险 | 敏感代码泄露 | 低 | 极高 |
| 安全风险 | Agent 误操作导致生产事故 | 低 | 极高 |
| 人员风险 | 关键人员离职导致知识断层 | 低 | 中 |
| 成本风险 | Agent 使用成本超出预算 | 中 | 中 |

### 7.2 应对预案

**技术风险应对**：

- **代码质量不稳定**：建立三级验证体系（自动验证 + 自动 Review + 人工 Review）；从简单任务开始，逐步增加复杂度
- **CI/CD 配置复杂**：先配置最简流水线（lint + test），逐步扩展；提供模板和文档

**流程风险应对**：

- **团队抵触**：从志愿者开始试点，展示成功案例；提供培训和支持
- **Review 瓶颈**：Agent 自动 Review 处理低风险变更；人工聚焦高风险变更

**安全风险应对**：

- **代码泄露**：使用企业版或私有化部署；建立代码分级（公开/内部/机密）
- **误操作**：严格权限控制；禁止 Agent 直接操作生产环境；所有变更需人工审批

**成本风险应对**：

- 设置 Token 预算上限；按月监控成本；异常消耗自动报警

### 7.3 人员培训计划

| 培训内容 | 对象 | 形式 | 时长 |
|----------|------|------|------|
| Agent 工具基础使用 | 全体研发 | 工作坊 | 2h |
| Plan Mode 工作流 | 开发工程师 | 实操演练 | 3h |
| `CLAUDE.md` 编写规范 | 架构师/TL | 评审会 | 2h |
| 安全使用规范 | 全体研发 | 线上课程 | 1h |
| CI/CD 流水线使用 | 开发工程师 | 文档 + 实操 | 2h |

---

## 八、效果评估与持续优化

### 8.1 量化评估指标体系

**效率指标**：

| 指标 | 定义 | 目标值 |
|------|------|--------|
| Agent 辅助代码占比 | Agent 生成或修改的代码行数 / 总代码行数 | > 30% |
| 任务完成时间 | 从任务分配到 MR 合并的平均时间 | 缩短 30% |
| 人均产出 | 每人每月完成的 Story Point | 提升 20% |

**质量指标**：

| 指标 | 定义 | 目标值 |
|------|------|--------|
| Agent 任务成功率 | Agent 辅助任务一次通过验证的比例 | > 70% |
| 返工率 | Agent 生成代码需要返工的比例 | < 30% |
| Bug 引入率 | Agent 辅助代码引入的 Bug 数 / 总 Bug 数 | < 15% |

**成本指标**：

| 指标 | 定义 | 目标值 |
|------|------|--------|
| 单任务成本 | 平均每个 Agent 辅助任务的 Token 成本 | 可控范围内 |
| 月度总成本 | 每月 Agent 使用总成本 | 在预算内 |

**满意度指标**：

| 指标 | 定义 | 目标值 |
|------|------|--------|
| 工具满意度 | 研发团队对 Agent 工具的满意度评分 | > 4/5 |
| 流程接受度 | 认为新流程提升效率的比例 | > 70% |

### 8.2 持续优化机制

**双周回顾会**：

- 回顾 Agent 辅助任务的成功案例和失败案例
- 更新 `CLAUDE.md` 和 Skills
- 调整工作流和规则

**月度度量报告**：

- 汇总效率、质量、成本指标
- 识别瓶颈和改进点
- 向管理层汇报

**季度复盘**：

- 评估整体目标达成情况
- 调整实施路线图
- 更新风险评估

**规则迭代流程**：

```
发现问题
  → 记录到问题清单
  → 分析根因（是规则问题、工具问题还是流程问题）
  → 更新 `CLAUDE.md` 或 Skills
  → 在试点项目验证
  → 推广到所有项目
  → 归档到知识库
```

---

## 九、样例模板

### 9.1 CLAUDE.md 模板

```markdown
# 项目目标
- 我们优先保证：正确性 > 可维护性 > 性能

# 代码与风格
- 只改与任务相关的文件，避免大范围重排
- 新增代码必须有对应测试（或解释为什么没有）
- 遵循现有代码风格，不引入新风格

# 关键命令（必须用这些验证）
- 安装：pnpm install
- 开发：pnpm dev
- 单测：pnpm test
- 类型：pnpm typecheck
- 格式化：pnpm format
- Lint：pnpm lint

# 架构边界
- HTTP handlers live in `src/http/handlers/`
- Domain logic lives in `src/domain/`
- Do not put persistence logic in handlers

# NEVER
- Modify `.env`, lockfiles, or CI secrets without explicit approval
- Remove feature flags without searching all call sites
- Commit without running tests
- Directly push to main branch

# ALWAYS
- Show diff before committing
- Update CHANGELOG for user-facing changes
- Run full test suite before MR

# 已知坑
- 不要直接改 X：因为线上依赖了 Y 的边界行为
- 任何对外 API 的变更必须同时更新 Z
```

### 9.2 Plan Mode 模板

```markdown
## 目标（1 句话）
实现用户登录接口的密码加密功能

## 现状
- 当前密码以明文存储
- 已有用户表结构，不能破坏现有数据
- 使用 bcrypt 库进行加密

## 约束
- 技术栈：Node.js + TypeScript + Prisma
- 不能改的接口：现有登录 API 的输入输出格式
- 性能：加密耗时 < 100ms
- 安全：密码不可逆，加盐存储

## 验收标准
- 通过 `pnpm test:auth` 测试
- 新注册用户密码加密存储
- 旧用户密码迁移方案（可选）
- 登录验证使用加密比对

## 风险点
1. 旧用户数据迁移可能影响登录
2. 加密性能可能影响用户体验

请先给出方案对比与最终计划（含步骤与回滚），确认后再改代码。
```

### 9.3 Skill 模板

```markdown
# Skill: code-change-verification

## 描述
当变更影响运行时代码、测试或构建行为时，运行强制验证流程

## 触发条件
- 修改了 `src/` 目录下的代码
- 修改了测试文件
- 修改了构建配置

## 执行步骤
1. 运行 `pnpm lint`
2. 运行 `pnpm typecheck`
3. 运行 `pnpm test`
4. 运行 `pnpm build`
5. 检查测试覆盖率是否下降

## 输出
- 验证结果（通过/失败）
- 失败时的具体错误信息
- 覆盖率变化报告

## 参考资料
- `tests/README.md`
- `package.json` scripts
```

### 9.4 AGENTS.md 模板

```markdown
# Agent 工作规则

## 强制触发规则
- 修改可能影响兼容性边界的运行时代码或 API 前，先调用 `$implementation-strategy`
- 代码、测试、示例或构建行为发生变化时，必须跑 `$code-change-verification`
- 涉及外部平台集成时，必须走 `$platform-knowledge`
- 工作完成准备交接时，调用 `$pr-draft-summary`

## 架构边界
- HTTP handlers live in `src/http/handlers/`
- Domain logic lives in `src/domain/`
- Do not put persistence logic in handlers

## NEVER
- Modify `.env`, lockfiles, or CI secrets without explicit approval
- Remove feature flags without searching all call sites
- Commit without running tests

## ALWAYS
- Show diff before committing
- Update CHANGELOG for user-facing changes
```

### 9.5 安全审查 Checklist 模板

```markdown
## Agent 生成代码安全审查

- [ ] 是否引入新的依赖？依赖是否可信？
- [ ] 是否涉及网络请求？目标地址是否白名单？
- [ ] 是否处理用户输入？是否有注入风险？
- [ ] 是否涉及权限变更？是否最小权限？
- [ ] 是否包含加密/哈希操作？算法是否合规？
- [ ] 是否涉及文件操作？路径是否受控？
- [ ] 是否涉及数据库操作？是否有 SQL 注入风险？
- [ ] 是否涉及敏感数据？是否脱敏处理？
- [ ] 是否符合公司安全规范？
- [ ] 是否通过安全测试？
```

---

## 十、附录

### 10.1 参考资料

基于 `articles/` 目录分析提取的关键文章：

1. 《把 Claude Code 用成工程工具：8 条黄金法则与一套可复用工作流》
2. 《Claude Code 最佳实践：可验证、可治理、可分层的工程现实》
3. 《OpenAI 工程师不写代码了？拆开 Harness Engineering 看看他们到底在干嘛》
4. 《从误删邮箱到 Skill 投毒：OpenClaw 安全到底该怎么做》
5. 《Agent Harness 综述：同一个模型，为什么做出来的 Agent 差这么远》
6. 《多 Agent 不是虚拟公司：从 Anthropic 五种模式看信息流怎么设计》
7. 《Sub-Agent VS Agent Team：多智能体架构和上下文边界》
8. 《OpenAI 怎么把开源项目维护做成工作流：Skills、AGENTS.md 和 CI 的一套组合拳》
9. 《Google 工程师用 Claude Code 自动化 80%？模型会变，软件工程会留下》
10. 《Spec 不是代码的替代品，它是 AI Coding 的上下文管理层》
11. 《你的 AI-First 对了吗？让我们一起看看你的软件工程成熟度》

### 10.2 关键术语

| 术语 | 说明 |
|------|------|
| Harness | 包住模型的整套运行系统，解决模型与真实工程世界的协作问题 |
| Skills | 将团队经验沉淀为 Agent 可复用的工作单元 |
| AGENTS.md | 项目级规则文件，声明 Agent 工作的触发条件、行为约束和必经流程 |
| Plan Mode | 先规划再执行的工作模式，避免 Agent 盲目动手 |
| Sub-Agent | 父 Agent 派出的独立上下文子任务执行者 |
| Context Management | 管理 Agent 的上下文窗口，包括截断、摘要、去重 |
| Hooks | 在 Agent 执行特定操作时触发的自动化检查 |

### 10.3 实施计划维护

- 本计划存放于 `docs/exec-plans/coding-agent-implementation-plan.md`
- 每季度回顾更新
- 变更需经架构师和研发负责人审批
