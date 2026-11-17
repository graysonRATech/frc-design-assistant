# FRC Design RAG Agent — Discovery

_Date: 2026-11-15 · Status: discovery complete, decisions recorded (see §9–11)_

## 1. Goal

A hosted assistant that students can use during the season. It answers FRC **design, CAD (Onshape), and fabrication** questions from a curated knowledge base, and every answer cites its source. Adding a new website or document to the knowledge base should take a one-line change, not engineering work.

Priorities, in order: **affordability → usability → auditability → uptime → scalability.** The scale is a classroom: about 40 students, with peaks during build season.

## 2. First source: frcdesign.org (verified 2026-11-15)

| Fact | Finding | Implication |
|---|---|---|
| Stack | Astro + Starlight static site on Cloudflare | Pages are clean, server-rendered HTML. No JS rendering is needed. |
| Size | `sitemap-0.xml` lists **170 URLs**. The repo has **171 `.md/.mdx`** files under `src/content/docs/` | Small corpus: roughly 0.3–0.6M tokens, ~1–3k chunks. Embedding cost is pennies. |
| Source repo | `github.com/frcdesign/FRCDesign.org` (public) | **Ingest from the repo, not by crawling.** The MDX has clean headings and frontmatter and no nav or sponsor boilerplate. Use `git pull` plus diffs to detect changes. |
| Sections | Learning Course (~110 pages), Design Handbook, Mechanism Examples, Best Practices, Educator's Guide, Resources | Store `section` as metadata for filtering and display. |
| robots.txt | 404 (none) | Not permission. Crawl politely, if at all. |
| License | **None found.** GitHub reports `license: null` and there's no footer notice | **Action:** ask the maintainers (Discord: discord.gg/frcdesign) before ingesting. Always link back to the page and never republish whole pages. |
| Content quirks | Many images have empty alt text. Onshape links sit inside MDX components (`ContentFigure`, `ImageTable`, `Aside`, `Slides`) | The ingestion step has to flatten MDX components into text and keep the Onshape links as references. Images are text-only in v1. |

Mapping: the URL is the repo path minus `src/content/docs/` and the extension, e.g. `learning-course/stage1/1b/gears.mdx` → `https://www.frcdesign.org/learning-course/stage1/1b/gears/`.

## 3. Candidate future sources (check permission for each)

| Source | Type | Notes |
|---|---|---|
| Vendor docs (WCP, REV, AndyMark, Thrifty Bot, Swerve Drive Specialties) | Product docs/PDFs | Usually fine to reference. Good for "which bearing/gear fits" questions. |
| FRC Game Manual (current season) | PDF | FIRST copyright. Very valuable for rules questions. Re-ingest when the manual is updated. |
| Team technical binders and build blogs (e.g. 254, 1678, 6328, 971) | PDFs/web | Ask each team, or link only. |
| Chief Delphi | Forum (Discourse) | Check the ToS. Prefer curated threads exported via the Discourse API over scraping. |
| Your own team docs (Google Drive, Onshape notes) | Docs | Highest value for "how does *our* team do it". |

## 4. Options considered

### Option A — AWS serverless + Bedrock Knowledge Base on S3 Vectors (**recommended**)

```
sources.yaml ─► GitHub Action (ingest) ─► S3 (normalized .md + .metadata.json)
                                             │
                                             ▼
                               Bedrock Knowledge Base (vector store: S3 Vectors)
                                             ▲ Retrieve
Student ─► Static web UI (S3+CloudFront/Amplify) ─► Cognito login ─► API Gateway ─► Lambda
                                                                        │  Claude on Bedrock (answer + citations)
                                                                        └► DynamoDB (Q&A audit log, feedback, rate limits)
```

- **Vector store: S3 Vectors, *not* OpenSearch Serverless.** OpenSearch Serverless has a **floor cost of roughly $175–345/month even with no traffic**, which rules it out here. S3 Vectors is a supported Knowledge Base store and costs cents at this corpus size.
- **Knowledge Bases have no fee of their own.** You pay for embeddings, storage, and model tokens.
- **Chunking: we pre-chunk and the KB uses "no chunking".** Our ingester splits on H2/H3 headings into chunks of about 300–800 tokens. It prepends the page title and breadcrumb ("Design Handbook › Fasteners › …"), and writes `source_url`, `section`, `source_id`, and `ingested_at` to the metadata. This keeps chunking under our control and portable to another vector store.
- **Agent layer:** v1 is a single Lambda that does retrieve → generate. **AgentCore** (Runtime/Memory/Gateway) is consumption-billed, with idle time free. It's a good v2 upgrade if we add tools (a gear-ratio or belt-length calculator, a game-manual lookup) or multi-turn memory, but it isn't needed for cited Q&A.
- Pros: you already know AWS, almost everything is pay-per-use, the services are managed and multi-AZ, and IAM, CloudTrail, and CloudWatch handle auditing.
- Cons: not strictly fixed cost (budget alarms mitigate this). New accounts get **low default Bedrock token quotas**, so request an increase before kickoff.

### Option B — Cloudflare (AI Search / Vectorize + Workers)
- The $5/month Workers Paid plan is close to fixed cost. AI Search (formerly AutoRAG) is a managed crawl → index → retrieve service. The free plan's binding limit is **500 pages/day indexed**, which is fine for this corpus. AI Search **started metered billing (~$0.75/M tokens) around Nov 1**, so confirm the current rates.
- Pros: cheapest fixed floor and a simple deployment.
- Cons: less mature audit and identity tooling, a new stack for you, and Claude is still billed separately through the API.

### Option C — Single small VPS (pgvector + FastAPI)
- Truly fixed hosting (about $5–12/month) plus LLM tokens.
- Cons: you own patching, backups, and uptime, and there's a single point of failure mid-season. **Not recommended** for a teacher-maintained system.

**Recommendation: Option A.** It fits your AWS experience, costs close to $0 when idle, and has the best auditability. Keep the ingester output (Markdown + metadata) store-agnostic so a move to B stays cheap.

## 5. Cost estimate (Option A)

Assumptions: 40 students, **1,000–3,500 questions/month** in peak season. Each question uses about 6k input tokens (system prompt + ~5 chunks + short history) and about 700 output tokens.

| Model (Anthropic list price, per 1M in/out) | Cost / question | 1,000 q/mo | 3,500 q/mo |
|---|---|---|---|
| Claude Opus 5.5 ($4 / $20) | ~$0.04–0.05 | ~$45 | ~$160 |
| Claude Sonnet 5.5 ($2 / $10) | ~$0.02 | ~$20 | ~$70 |
| Claude Haiku 5.5 ($0.10 / $0.50) | ~$0.001 | ~$1 | ~$4 |

Bedrock prices for Claude are set by AWS and may differ from Anthropic's list prices. Check the [Bedrock pricing page](https://aws.amazon.com/bedrock/pricing/). Thinking tokens bill as output, so the Opus row assumes effort `medium` (the default) and includes a buffer.

| Other components | Expected monthly |
|---|---|
| Embeddings (full re-index of ~0.5M tokens) | < $0.05 per re-index |
| S3 + S3 Vectors storage/queries | < $1 |
| Lambda, API Gateway, DynamoDB on-demand, Cognito (<10k MAU) | ~$0 (within always-free allowances) |
| CloudFront/Amplify static hosting | ~$0–1 |
| CloudWatch logs (30-day retention) | ~$0–2 |
| **Infra total** | **≈ $1–5 / month** |

**AWS Free Tier reality (2026):** new accounts get **$100 in credits plus up to $100 more** under a **6-month "Free plan"**. At the end of that plan the account is **closed unless upgraded** (90-day recovery window). For a season-long service, **use a Paid-plan account** (the credits still apply) and set AWS Budgets alerts at $10/$25/$50. Confirm that Bedrock usage counts against your credits in the Billing console.

The model choice is the real cost lever. In v1 the model is a config value, so you can switch it in one setting and compare answer quality on an eval set (§8).

## 6. Requirements mapped to the design

| Concern | Design decision |
|---|---|
| **Uptime** | Every component is a managed, multi-AZ serverless service, with no servers to patch. Bedrock throttling is the main risk: request a quota increase and add retry/backoff. A friendly fallback message links to frcdesign.org search. Add a CloudWatch alarm on 5xx/throttles. |
| **Scalability** | Lambda/API Gateway scale automatically. S3 Vectors handles millions of vectors, so the corpus can grow 100× without architecture changes. |
| **Auditability** | DynamoDB logs every turn: hashed user ID, question, retrieved chunk IDs and URLs, model ID, prompt version, token counts, latency, and 👍/👎 feedback. CloudTrail covers admin actions. `sources.yaml` and the prompts live in git, so the history shows who added what and when. Each ingestion run writes a manifest (source → files → content hashes). |
| **Usability** | A simple chat UI, mobile-friendly for the shop floor. Answers cite sources (title + link + section). It says "I don't know" when retrieval is weak, and keeps follow-up context for a short conversation. Example prompts show students what to ask. |
| **Affordability** | Close to $0 when idle and pay-per-question. There's a per-student daily cap (e.g. 40 q/day) enforced in DynamoDB, a `max_tokens` cap, Lambda reserved concurrency as a circuit breaker, and AWS Budgets alarms. |
| **Safety (minors)** | Cognito login, invite-only through a class code or school-domain email. Store no PII beyond a hashed ID. The system prompt keeps answers on FRC design/CAD/fabrication, with shop-safety reminders on fabrication answers. Bedrock Guardrails are optional (per-text-unit cost). |

## 7. Streamlined knowledge-base updates

A single file in the repo is the source of truth:

```yaml
# sources.yaml
- id: frcdesign
  type: github_repo            # github_repo | sitemap | url_list | pdf | gdrive_folder
  repo: frcdesign/FRCDesign.org
  path: src/content/docs
  url_template: "https://www.frcdesign.org/{path}/"
  license_status: pending      # pending | permitted | link-only
  refresh: weekly
- id: wcp-docs
  type: sitemap
  url: https://docs.wcproducts.com/sitemap.xml
  include: ["/docs/**"]
  license_status: pending
  refresh: monthly
```

**Workflow:** open a pull request that adds an entry → review → merge. A GitHub Action then runs the ingester. It fetches the source, converts it to Markdown, strips boilerplate, chunks by heading, attaches metadata, uploads to `s3://…/kb/{source_id}/`, and calls `StartIngestionJob`. A scheduled run handles each source's `refresh` cadence. Only changed files are re-uploaded, based on content hashes. Deleted pages are removed from S3, so the KB drops them on the next sync.

For one-off additions (a PDF or a team doc), a small admin page or CLI (`kb add <url|file> --source my-team`) uses the same path.

## 8. Quality plan

- **Eval set:** before launch, write 30–50 real student questions with the expected source pages (drivetrain gearing, bolt patterns, 3D-print tolerances, Onshape mate types, and so on). Re-run it whenever the prompt, model, or chunking changes.
- **Retrieval tuning:** try top-k 5–8 and hybrid search (semantic plus keyword helps part numbers like "#25 chain" or "WCP-0123"). Optionally rerank.
- **Feedback loop:** review 👎 answers weekly. Missing content goes into `sources.yaml`, and bad answers update the prompt or the eval set.

## 9. Decisions (2026-11-15)

1. **Content use:** attribute every source in answers (title + link) and in the README. No formal license is being pursued. The codebase is open source, but **usage is locked to our team** because we pay for it.
2. **Model:** start with **Claude Sonnet 5.5** (`anthropic.claude-sonnet-5-5` on Bedrock), effort `low` for chat, then re-tune using the eval set. The model is a config value.
3. **AWS:** a Paid-plan account in **us-east-1**, with layered budget controls (§11).
4. **Identity:** students sign in with **Google accounts** (§10).
5. **IaC:** **AWS CDK in Python.** Cost is the same either way: both tools are free, and CloudFormation is free for AWS resources. CDK has no state backend to run, while Terraform needs an S3 state bucket (pennies). Using Python everywhere (ingester, Lambdas, infra) gives students one language to learn.

## 10. Authentication & authorization

```
Browser ─► Cognito Hosted UI ─► "Sign in with Google" ─► Cognito issues JWT (with cognito:groups)
   │                                  │ Pre-sign-up / Pre-token Lambda: email on allowlist? else reject
   ▼
API Gateway (HTTP API) JWT authorizer ─► Lambda checks group (student | mentor | admin) ─► Bedrock
```

- **Authentication:** a Cognito User Pool with Google as a federated identity provider. Students sign in with their existing Google accounts, and we store no passwords. Social-federated users fall within Cognito's free MAU allowance at our scale.
- **Authorization (allowlist, not "any Google account"):** a Cognito **Pre-sign-up trigger** rejects any email that isn't on the team allowlist, so random Google users get "not authorized". If students share a school Workspace domain, a domain rule (`*@school.org`) can replace per-email entries. A **Pre-token-generation trigger** re-checks the allowlist on every sign-in or refresh, so removing a student cuts off access within the token lifetime (set to 1 hour).
- **Roles:** Cognito groups. `student` can chat. `mentor` can also view the audit log and feedback. `admin` can also manage the allowlist and trigger ingestion.
- **API enforcement:** the API Gateway JWT authorizer rejects unauthenticated calls before any Lambda runs, so they cost nothing. The Lambda checks the group claim and the per-user rate limit.
- **Open-source hygiene:** the allowlist (student emails are minors' PII) lives in DynamoDB, never in git. The Google OAuth client secret lives in Secrets Manager (~$0.40/month). An SSM SecureString would be free, but CloudFormation can't resolve SecureStrings into Cognito identity-provider properties, and the alternative of passing the secret at deploy time would write it into the template in plaintext. GitHub Actions deploys with **OIDC role assumption**, with no long-lived AWS keys. Account- and team-specific values sit in an untracked `config.local.yaml` with a committed `config.example.yaml`, so other teams can fork and deploy their own copy.
- **Management:** `kb users add|remove|list <email> [--role mentor]` writes to the allowlist table, and an admin page can follow later.

## 11. Budget controls (layered, because AWS billing data lags ~8–24 h)

1. **App-level hard caps (real-time):** per-user daily and global monthly **spend counters** in DynamoDB, metered in micro-dollars from each response's token usage (defaults: $0.50 per student per day, about 40 questions, and $20 per month). Past a cap the API returns "limit reached" until the counter resets. *(Implemented in phase 2: `backend/chat_api/usage.py`.)*
2. **Per-request caps:** `max_tokens` on responses, bounded retrieval (top-k ≤ 8), and a bounded conversation history.
3. **Concurrency circuit breaker:** reserved concurrency on the chat Lambda (`lambda_reserved_concurrency`). New accounts have a 10-execution quota and can't reserve any until AWS raises it, so the default is off.
4. **AWS Budgets alerts:** email at 50/80/100% of the monthly budget, plus a forecast alert.
5. **AWS Budgets action (kill switch):** at 120% of budget, attach an IAM deny policy for `bedrock:*` and `bedrock-mantle:*` to the chat Lambda and Knowledge Base roles. This stops spend even if the app caps have a bug. An admin removes the policy to restore service.
6. **Cost tags:** tag every resource with `project=frc-rag` so Cost Explorer shows a clean per-project view.

## 12. Proposed phases

1. **Ingest:** `sources.yaml`, an ingester for `github_repo` and `sitemap` sources, and a local chunk preview. Covers frcdesign.org.
2. **KB + API:** CDK stack for S3, S3 Vectors, the Bedrock KB, the chat Lambda, the DynamoDB log, and the Budgets alerts and kill switch. CLI chat for testing, plus the eval harness. The Lambda is reachable only through IAM (`lambda:InvokeFunction`), so nothing is public until phase 3 adds API Gateway with the Cognito authorizer.
3. **Student UI + auth:** static chat page, API Gateway, Cognito with Google sign-in and the allowlist, citations, and feedback.
4. **Operations:** GitHub Actions for ingestion and deploys, a weekly review dashboard, and new sources.
5. **(Optional) Agent tools:** AgentCore or tool use for calculators (gear ratio, belt/chain center distance, motor curves) and game-manual lookup.

## Sources
- [AWS Free Tier](https://aws.amazon.com/free) · [Free Tier FAQs](https://aws.amazon.com/free/faqs/) · [Free Tier credits announcement (Jul 2025)](https://aws.amazon.com/about-aws/whats-new/2025/07/aws-free-tier-credits-month-free-plan)
- [Bedrock AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/) · [Bedrock pricing](https://aws.amazon.com/bedrock/pricing/)
- [S3 Vectors query-price reduction (Jun 2026)](https://aws.amazon.com/about-aws/whats-new/2026/06/s3-vectors-reduces-query-charges-80-percent-large-indexes) · [Bedrock KB cost trap / OpenSearch floor](https://cloudburn.io/blog/amazon-bedrock-pricing) · [KB cost optimization 2026](https://www.factualminds.com/blog/bedrock-knowledge-base-cost-optimization-2026/)
- [Cloudflare AI Search limits & pricing](https://developers.cloudflare.com/ai-search/platform/limits-pricing) · [AI Search billing start](https://ppc.land/cloudflare-ai-search-starts-billing-november-1-at-0-75-per-million-tokens/)
- [FRCDesign.org repo](https://github.com/frcdesign/FRCDesign.org)
