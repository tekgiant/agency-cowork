# Email Triage Summary — {{DATE}} {{TIME}} PT

{{#if urgent_count}}
## 🔴 URGENT ({{urgent_count}})

{{#each urgent}}
- **{{subject}}** — from {{sender}}
  {{summary}}
  📧 [Open in Outlook]({{web_link}}){{#if draft_id}} | 📝 Draft ready{{/if}}

{{/each}}
{{/if}}

{{#if needs_response_count}}
## 🟡 NEEDS RESPONSE ({{needs_response_count}})

{{#each needs_response}}
- **{{subject}}** — from {{sender}}
  {{summary}}
  📧 [Open in Outlook]({{web_link}}){{#if draft_id}} | 📝 Draft ready{{/if}}

{{/each}}
{{/if}}

{{#if fyi_count}}
## 🟢 FYI — Archived ({{fyi_count}})

{{#each fyi}}
- **{{subject}}** — from {{sender}} — {{summary}}
  📧 [Open in Outlook]({{web_link}})

{{/each}}
{{/if}}

{{#if noise_count}}
## 🗑️ NOISE FILTERED ({{noise_count}})

Auto-archived: {{noise_summary}}
{{/if}}

---
*Triage run #{{run_number}} | {{total_processed}} emails processed | Next run: {{next_run}}*
