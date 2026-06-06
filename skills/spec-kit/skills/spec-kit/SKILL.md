---
name: spec-kit
description: This skill should be used when the user asks to "create a spec", "write a specification", "plan a feature", "initialize spec-driven development", "generate a constitution", "break down tasks", "implement from spec", or wants to use spec-driven development to plan and build software systematically. Triggers include "spec-kit", "speckit", "specify", "spec-driven", "create a plan", "generate tasks from spec", or "implement the plan".
---

Use GitHub Spec Kit for spec-driven development — turning specifications into executable implementations through a structured pipeline.

## Overview

Spec Kit is an open-source toolkit from GitHub that replaces "vibe coding" with a structured, spec-driven workflow. Instead of jumping straight into code, you define **what** and **why** first, then systematically plan and implement. The toolkit provides slash commands (`/speckit.*`) that guide the full lifecycle from project principles to implementation.

## Prerequisites

Before using this skill, ensure:
1. **Python 3.11+** is installed
2. **uv** package manager is installed
3. **Specify CLI** is installed (see installation below)

Check prerequisites:

```bash
specify check
```

## Installation Check

If `specify` is not installed, install it:

```bash
uv tool install specify-cli --from git+https://github.com/github/spec-kit.git
```

To upgrade:

```bash
uv tool install specify-cli --force --from git+https://github.com/github/spec-kit.git
```

## Workflow

### Step 1: Initialize the Project

If the project doesn't already have a `.speckit/` directory, initialize it:

```bash
specify init . --ai claude
```

This creates the `.speckit/` directory structure with slash commands and templates.

If already initialized, skip to Step 2.

### Step 2: Establish a Constitution

Use `/speckit.constitution` to create governing principles for the project. This defines code quality standards, testing requirements, and architectural guidelines that all subsequent work must follow.

```
/speckit.constitution Create principles focused on code quality, testing standards, and performance requirements
```

The constitution is saved to `.speckit/memory/constitution.md`.

### Step 3: Create a Specification

Use `/speckit.specify` to describe what should be built. Focus on the **what** and **why** — scenarios and outcomes, not implementation details.

```
/speckit.specify Build a REST API that manages user authentication with JWT tokens, supporting login, logout, and token refresh
```

The spec is saved to `.speckit/features/<feature-name>/spec.md`.

### Step 4: Plan the Implementation

Use `/speckit.plan` to generate a detailed implementation plan from the spec.

```
/speckit.plan
```

This creates `.speckit/features/<feature-name>/plan.md` with architecture decisions, component breakdown, and implementation strategy.

### Step 5: Generate Tasks

Use `/speckit.tasks` to break down the plan into ordered, actionable tasks with dependency management.

```
/speckit.tasks
```

This creates `.speckit/features/<feature-name>/tasks.md` with:
- Tasks organized by user story
- Dependency ordering
- Parallel execution markers `[P]`
- File path specifications
- Test-driven development structure

### Step 6: Implement

Use `/speckit.implement` to execute the task plan:

```
/speckit.implement
```

This validates prerequisites, parses `tasks.md`, and executes tasks in order respecting dependencies.

### Additional Commands

- **`/speckit.analyze`** — Analyze the existing codebase for patterns, architecture, and potential issues
- **`/speckit.clarify`** — Clarify ambiguous requirements through structured questioning
- **`/speckit.checklist`** — Generate a pre-implementation checklist
- **`/speckit.taskstoissues`** — Convert tasks.md into GitHub Issues (requires GitHub CLI)

## Rules

- ALWAYS check if `specify` CLI is installed before attempting to use it
- ALWAYS check if the project has been initialized (`.speckit/` directory exists) before running commands
- The constitution should be established before creating specs — it guides all subsequent decisions
- Specs should focus on **what** and **why**, not **how** — let the planning phase handle implementation details
- Review the generated plan with the user before proceeding to tasks or implementation
- When using `/speckit.implement`, ensure all prerequisite files exist (constitution, spec, plan, tasks)
- Do not skip phases — the pipeline is designed to be followed in order for best results
- If the user only wants a specific phase (e.g., just planning), that's fine — but note what's missing
