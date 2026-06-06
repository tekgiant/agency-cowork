---
name: d365-expense
description: >
  Create expense reports in Microsoft Dynamics 365 Finance & Operations via
  Playwright browser automation. Corporate card (Amex) charges already appear
  in D365 — this skill creates a new report, attaches those charges, and sets
  approvers. Triggers: "expense report", "file expense", "submit expense",
  "expense reimbursement", "D365 expense".
---

# D365 Expense Report Skill

## Overview

Create expense reports in D365 Finance & Operations. Corporate card (Amex) transactions already appear in the Expenses tab automatically — you do NOT need to create individual expense lines. This skill uses Playwright to open the D365 workspace, create a new report, attach existing card transactions, and set approvers.

**Workspace URL:** `https://myexpense.operations.dynamics.com/?cmp=1010&mi=ExpenseWorkspace`

**All scripts run from the project root:**

```bash
python skills/d365-expense/scripts/expense.py --action navigate
```

## Defaults

| Field             | Default Value                            |
|-------------------|------------------------------------------|
| Interim approver  | Maila Lee                                |
| Final approver    | Tarri Edmonson                           |
| Cost center (CC)  | 10217334 (RESILIENCY-COGS-1010-BB)       |

If the user specifies different values, use theirs without asking for confirmation.

The final approver field in D365 often defaults to someone else — always verify and correct it.

## Before Starting — Collect in One Message

Ask the user for all of these at once:

1. **Report name** (e.g. "KubeCon NA 2026", "March misc")
2. **Description** (brief purpose of the report)
3. **Interim approver** (default: Maila Lee — confirm or override)
4. **Final approver** (default: Tarri Edmonson — confirm or override)

Corporate card charges are already in D365. Do NOT ask the user to list individual expenses.

## Workflow

### Step 1 — Navigate to workspace

```bash
python skills/d365-expense/scripts/expense.py --action navigate
```

Read the returned screenshot to confirm the workspace loaded. If the Expenses tab shows Amex charges, proceed.

### Step 2 — Create new expense report

Use the script's interactive primitives to drive the D365 UI:

1. **Click** `+ New expense report` from the Reports tab
2. **Fill in** the "New expense report" panel:
   - **Description:** from the user
   - **Expenses:** select "Add all (N)" to attach all open corporate card transactions
   - **Interim approvers:** type the approver name (default: Maila Lee)
   - **Final approver:** verify the dropdown — change to the correct name if wrong (default: Tarri Edmonson)
   - **CC:** 10217334 (RESILIENCY-COGS-1010-BB)
3. **Click** Create

Available CLI primitives for each step:

```bash
# Click a button by visible text
python skills/d365-expense/scripts/expense.py --action click --text "New expense report"

# Fill a field by aria-label or D365 control name
python skills/d365-expense/scripts/expense.py --action fill --label "Description" --value "KubeCon NA 2026"

# Select a dropdown option
python skills/d365-expense/scripts/expense.py --action select --label "Final approver" --value "Tarri Edmonson"

# Take a screenshot to verify state
python skills/d365-expense/scripts/expense.py --action screenshot

# Read page state (buttons, inputs, visible text)
python skills/d365-expense/scripts/expense.py --action state
```

### Step 3 — Stop here and hand off to user

After the report is created with expenses attached:

1. **Take a screenshot** to confirm the report was created successfully
2. **Tell the user** they need to:
   - Open the report in D365 to attach receipts manually
   - Provide the direct link: `https://myexpense.operations.dynamics.com/?cmp=1010&mi=ExpenseWorkspace`
   - Review and submit the report themselves

**Do NOT attempt to:**
- Submit the report on behalf of the user
- Upload or attach receipt images via automation
- Create individual draft expense lines — corporate card charges already exist

## Category Reference (for user's information only)

| Expense type                              | D365 category              |
|-------------------------------------------|----------------------------|
| Flight / airfare                          | Airfare                    |
| Hotel base charge                         | Hotel                      |
| Hotel nightly room rate                   | Daily Room Rate            |
| Hotel taxes                               | Hotel Tax                  |
| Uber / Lyft / taxi / transit              | Ground Transportation      |
| Parking                                   | Parking                    |
| Meal during conference or business trip   | Meals \| Employee Travel   |
| Team lunch / morale event / DoorDash      | Meals \| Employee Morale   |
| Team gift / Amazon purchase for morale    | EE Morale - Gift & Entertain |
| Conference registration fee               | Conference                 |

**Meal category guidance:** Travel/conference venue meals → `Meals | Employee Travel`. Team lunch/offsite/morale → `Meals | Employee Morale`.

## D365 Quirks

- "Are you still there?" timeout dialog → click "I'm here" (handled by script)
- Network connectivity lost → click Reconnect (handled by script)
- Processing spinner stalls > 30s → refresh workspace URL
- Final approver field often defaults to wrong person — always verify and correct

## Rules

1. **Never create individual draft expense lines** — corporate card charges already appear in D365
2. **Never submit the report** — only create it and attach expenses, then hand off to user
3. **Always tell the user to attach receipts manually** via the D365 link
4. **Verify final approver** — the default is often wrong
5. **Take screenshots after each step** — to confirm state before proceeding

## CDP Port

This skill uses CDP port **9227** (unique per skill to avoid conflicts).

## Browser Profile

Stored at: `~/.d365-expense-agent/browser-profile/`
