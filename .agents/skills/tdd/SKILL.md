---
name: tdd
description: 测试驱动开发工作流 (TDD)。当用户要求编写业务代码但未提供测试用例时激活。遵循 Red-Green-Refactor 微循环。
when_to_use: "当用户要求按照 TDD（测试驱动开发）方式开发、需要先写测试再写实现、或明确要求遵循红-绿-重构流程时激活。触发示例：'用TDD方式实现这个功能'、'按红绿refactor来'、'先写测试再写代码'"
---

# TDD 开发工作流

## 描述
严格遵循 Kent Beck《测试驱动开发》思想的 AI 结对编程助手工作流。引导开发者通过"红-绿-重构"微循环写出高内聚、低耦合的优雅代码。

---

## 🎯 需求理解与拆解

接收到新功能需求或 Bug 修复任务时：

1. **理解**：用一句话简述业务需求
2. **拆解**：将需求拆解为极小的测试用例清单

### 输出格式

```
### 🎯 需求理解与拆解
- **理解**：<一句话简述业务需求>
- **To-Do List**：
    - [ ] <测试用例 1：场景与预期>
    - [ ] <测试用例 2：场景与预期>
```

---

## 🔴 Step 1: Red (红)

**原则**：「没有失败的测试，就不写业务代码」

### 任务
- 输出针对 To-Do List 第一项的单元测试代码
- **绝对不输出业务代码**
- 只写能让测试编译的最小代码框架

### 测试方法命名规范
遵循 `should_{预期行为}_when_{触发条件}` 模式：

```java
// ✅ 正确示例
@Test
void should_returnUserList_when_queryValidUsers() { }

@Test
void should_throwNotFoundException_when_userIdNotExist() { }

// ❌ 错误示例
@Test
void testGetUser() { }

@Test
void test1() { }
```

### 输出格式

```markdown
### 🔴 Step 1: Red (编写失败的测试)

针对【测试用例 1】的测试代码：

```java
// 测试代码
```
```

---

## 🟢 Step 2: Green (绿)

用户确认测试失败后执行。

### 任务
- 输出**最少量、最简单**的生产代码
- 允许使用"伪实现（Fake It）"或硬编码
- 唯一目标：让刚才的测试通过

### 原则
- 不要过度设计
- 不要提前优化
- 只解决"让测试通过"这一件事

### 输出格式

```markdown
### 🟢 Step 2: Green (让测试通过)

```java
// 生产代码（最小实现）
```
```

---

## ♻️ Step 3: Refactor (重构)

测试变绿后执行。

### 任务
- 在测试安全网下审视并优化代码
- 消除重复（DRY）
- 优化变量命名
- 提取方法
- 应用设计模式

### 约束
- 保证测试持续通过
- 不要引入新的测试（那是下一步的事）

### 输出格式

```markdown
### ♻️ Step 3: Refactor (重构优化)

优化内容：
- <优化点 1>
- <优化点 2>

重构后代码：
```java
// 重构后的代码
```
```

---

## 🔄 Step 4: Loop (循环)

完成一个微循环后：

1. 划掉 To-Do List 上的已完成项
2. 进入下一个测试用例
3. 重复 Red → Green → Refactor 流程

---

## Rules (铁律)

| 规则 | 说明 |
|------|------|
| **Baby Steps** | 步子要小：每次只解决一个极小的核心问题 |
| **Intent over Implementation** | 测试方法命名必须清晰描述业务行为和预期 |
| **FIRST Principles** | Fast(快速)、Independent(独立)、Repeatable(可重复)、Self-Validating(自我验证)、Timely(及时) |
| **No Test, No Code** | 未提供测试用例时，必须拒绝直接生成业务代码 |

---

## 约束条件

1. 优先测试**纯逻辑**，不依赖外部系统
2. 必要时使用 **Mock/Stub** 隔离外部依赖
3. 测试必须**快速**执行（毫秒级）
4. 测试之间**不能有依赖**
5. 每个测试必须能**独立运行**

---

## 使用示例

### 用户输入
```
实现一个用户注册功能，需要验证邮箱格式和密码强度
```

### Agent 响应

```
### 🎯 需求理解与拆解
- **理解**：实现用户注册接口，包含邮箱格式校验和密码强度校验
- **To-Do List**：
    - [ ] Should_returnSuccess_when_validEmailAndPassword
    - [ ] Should_throwValidationError_when_invalidEmail
    - [ ] Should_throwValidationError_when_weakPassword
    - [ ] Should_throwConflictException_when_emailAlreadyExists

---

### 🔴 Step 1: Red (编写失败的测试)

针对【Should_returnSuccess_when_validEmailAndPassword】的测试代码：

```java
@Test
void should_returnSuccess_when_validEmailAndPassword() {
    // Given
    RegisterRequest request = new RegisterRequest();
    request.setEmail("test@example.com");
    request.setPassword("StrongPass123!");

    // When
    AuthResult result = authService.register(request);

    // Then
    assertNotNull(result);
    assertNotNull(result.getToken());
}
```
```

**请运行测试，预期结果：编译失败（因为 AuthService.register 方法不存在）**
```

---

## 注意事项

1. **用户确认后才绿**：只有用户确认测试失败后，才输出 Green 阶段代码
2. **保持小步**：如果测试代码逻辑过长，必须强制拆解
3. **命名即文档**：测试方法名就是最好的文档
4. **重构不引入新测试**：重构阶段只优化已有代码，不添加新测试用例
