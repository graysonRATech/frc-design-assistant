# FRC Design RAG Agent

A cited Q&A assistant for FRC **design, CAD (Onshape) and fabrication** questions, built for a team's students to use during the season. Answers come from a curated knowledge base, and every answer links back to its source.

Architecture, costs and decisions are in [docs/discovery.md](docs/discovery.md).

## Status

| Phase | What | State |
|---|---|---|
| 1 | Ingestion: `sources.yaml` → normalized, chunked Markdown + metadata | ✅ |
| 2 | AWS stack (CDK): S3, Bedrock Knowledge Base on S3 Vectors, chat Lambda, audit log, budget guardrails | ✅ deployed; content load awaits Bedrock quotas |
| 3 | Student web UI, API Gateway, Google sign-in via Cognito, allowlist, feedback | ✅ deployed |
| 4 | GitHub Actions: tests, source previews on PRs, deploys, weekly content refresh | ✅ built; needs a GitHub repo |

## Knowledge sources

Sources live in [`sources.yaml`](sources.yaml). To add a website or repository, append an entry and open a pull request. The file header documents every field. The pull request runs the real ingestion and shows the document and chunk counts in its checks; once merged, the content workflow loads it into the knowledge base.

| Source | Content | Credit |
|---|---|---|
| [FRCDesign.org](https://www.frcdesign.org/) | Learning course, design handbook, mechanism examples, best practices | FRCDesign.org contributors, ingested from [frcdesign/FRCDesign.org](https://github.com/frcdesign/FRCDesign.org) |

Answers always cite and link to the original page. Content stays with its authors.

## Running the ingester

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run kb sources                         # list configured sources
uv run kb ingest                          # fetch + chunk every source into build/kb/
uv run kb ingest --source frcdesign       # just one source
uv run kb preview frcdesign --match fasteners --limit 2
uv run pytest
```

Set `GITHUB_TOKEN` to avoid GitHub's anonymous rate limit when ingesting often.

If Windows Application Control blocks the generated `kb.exe` launcher, run the same commands as `uv run python -m frcrag <command>`.

### Output layout

```
build/kb/<source_id>/<page>--NNN.md                 one chunk per file (Bedrock KB chunking: NONE)
build/kb/<source_id>/<page>--NNN.md.metadata.json   source, title, url, site section
build/kb/_manifests/<source_id>.json                 revision (e.g. commit SHA), hashes, timestamps
```

Each chunk begins with its page title, a section breadcrumb and a deep link, so it reads on its own:

```
# Fasteners
Section: Design Handbook > Bolt Sizes > Imperial
Source: https://www.frcdesign.org/design-handbook/structure/fasteners/#imperial
```

## Deploying to AWS

### What gets deployed

| Piece | Purpose |
|---|---|
| S3 bucket | Chunk files under `kb/`, ingest manifests under `manifests/` |
| S3 Vectors index + Bedrock Knowledge Base | Titan Text Embeddings V2 (1024-d); the data source uses chunking `NONE`, since files arrive pre-chunked |
| Chat Lambda (`backend/chat_api`) | Retrieves the top 6 chunks, asks Claude Sonnet 5.5 (effort `low`), returns the answer with cited sources |
| DynamoDB table | Audit log (question, answer, sources, tokens and cost per request; 365-day TTL) and spend counters |
| AWS Budgets | Email at 50/80/100% of the monthly budget and on forecast; at 120% an IAM deny on all Bedrock calls |
| Cognito user pool | Google sign-in only. Allowlist triggers (`backend/auth_triggers`) reject anyone not added with `kb users add`, on sign-up and on every token refresh |
| HTTP API | `POST /chat` and `POST /feedback`, both behind a Cognito JWT authorizer; throttled to 5 req/s |
| CloudFront + S3 | The chat page (`web/`, plain HTML/JS, no build step) with a strict Content-Security-Policy |

### One-time setup

`aws login` credentials aren't readable by the CDK CLI yet. Before `cdk` commands in PowerShell, run `aws configure export-credentials --format powershell | Out-String | Invoke-Expression`.

1. You need an AWS account on the **Paid plan**, the [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) signed in (`aws configure sso` or `aws login`), and Node.js 22 or newer for the CDK CLI.
2. In the [Bedrock console (us-east-1)](https://console.aws.amazon.com/bedrock/home?region=us-east-1#/modelaccess), enable **Claude Sonnet 5.5** and **Titan Text Embeddings V2**.
3. Copy `config.example.yaml` to `config.local.yaml` and set `account` and `alert_email`. Review the budget and limits.
4. Run:

   ```sh
   uv sync --group infra --group aws
   npx aws-cdk@2 bootstrap      # once per account/region
   ```

### Deploy and load content

```sh
npx aws-cdk@2 deploy            # builds the Lambda bundle (Linux arm64 wheels, no Docker) and deploys
uv run kb ingest                # chunk every source locally
uv run kb sync                  # upload changed chunks, delete stale ones, re-index the Knowledge Base
uv run kb eval                  # retrieval check against evals/retrieval.yaml (embeddings only, ~free)
uv run kb ask "How do I calculate gear center distance?"
```

`kb sync` mirrors **every** source in `sources.yaml`, and refuses to run if one hasn't been ingested, so a missing build can't wipe it from the knowledge base. Use `--dry-run` to preview changes.

### Google sign-in

1. In the [Google Cloud console](https://console.cloud.google.com/apis/credentials), create a project, configure the **OAuth consent screen** (External, app name "FRC Design Assistant", scopes `openid`, `email`, `profile`), then create an **OAuth client ID** of type *Web application*:
   - Authorized JavaScript origin: `https://<auth_domain_prefix>.auth.us-east-1.amazoncognito.com`
   - Authorized redirect URI: the `GoogleRedirectUri` stack output
2. Store the client secret in Secrets Manager (about $0.40/month):

   ```sh
   aws secretsmanager create-secret --region us-east-1 --name frcrag/google-oauth --secret-string '{"client_secret":"<secret>"}'
   ```

3. Put the client ID in `config.local.yaml` under `web.google_client_id` and run `npx aws-cdk@2 deploy` again.

### Managing who can sign in

```sh
uv run kb users add alex@example.org sam@example.org          # students (default role)
uv run kb users add --file roster.txt                         # one email per line; keep rosters out of git
uv run kb users add coach@example.org --role mentor
uv run kb users add @school.example.org                       # everyone with a verified school Google account
uv run kb users add former@school.example.org --role blocked  # one address the domain rule would let in
uv run kb users list
uv run kb users remove alex@example.org                       # revokes sessions and deletes their sign-in record
```

The allowlist is stored in DynamoDB, never in this repository. Feedback from the 👍/👎 buttons is stored next to the audit log (`pk = FEEDBACK`).

### Costs

At idle the stack costs about $0.40/month: the Google client secret in Secrets Manager. S3 Vectors, DynamoDB on-demand, Lambda, API Gateway, CloudFront and Cognito (Lite, under 10,000 monthly users) all bill per use or fall under free tiers, and the first two budgets are free. A question costs about $0.01–0.015, mostly Claude tokens: roughly 3.5k input and 500 output tokens. The app caps (`limits` in the config) stop spending before AWS Budgets has to.

If the Budgets kill switch fires, detach the `BudgetDenyBedrock` policy from the two roles in IAM to restore service, after raising the budget.

### Tests

```sh
uv run --group infra --group aws pytest    # includes CDK template assertions (~20 s)
```

### Custom domain

The site works at its CloudFront address out of the box. To serve it from your own name, such as `frc.example.org`:

1. Request a certificate in **us-east-1** (CloudFront only uses certificates from there):
   `aws acm request-certificate --region us-east-1 --domain-name frc.example.org --validation-method DNS`
2. Add the validation CNAME that `aws acm describe-certificate` shows at your DNS provider, and wait for the status `ISSUED`.
3. Set `web.domain_name` and `web.certificate_arn` in `config.local.yaml` and deploy.
4. Point the name at the `WebUrl` CloudFront host with a CNAME. On Cloudflare, set the record to **DNS only** (grey cloud): CloudFront already serves HTTPS, and proxying through Cloudflare breaks it.

The CloudFront address keeps working for sign-in, so old links don't break. Google needs no changes.

## Continuous deployment

Four workflows in [`.github/workflows`](.github/workflows), with actions pinned to commit SHAs:

| Workflow | Runs on | Does | AWS access |
|---|---|---|---|
| CI | every PR and push | tests, `sources.yaml` check, `cdk synth` | none |
| Preview sources | PRs touching sources or the ingester | real `kb ingest`, counts in the job summary | none |
| Deploy | push to main touching infra/backend/web; manual | tests, then `cdk deploy` | `FrcRag-github-deploy` |
| Refresh content | Mondays, merges touching sources; manual | `kb ingest`, `kb sync`, `kb eval` | `FrcRag-github-content` |

AWS access uses GitHub's OIDC tokens, so no AWS keys are stored in GitHub. The deploy role trusts only this repository's `production` environment; the content role trusts only its `main` branch and can only write the content bucket and re-index the Knowledge Base. Pull requests, including from forks, get neither.

One-time setup:

1. Push this code to a GitHub repository.
2. Set `github.repo: owner/name` in `config.local.yaml` and deploy once from your machine. This creates the OIDC provider and both roles.
3. In the repository settings:
   - **Variables:** `GOOGLE_CLIENT_ID` if sign-in is set up, and optionally `MODEL_CONFIG`: JSON overrides for the `model` block (for example `{"id": "us.anthropic.claude-haiku-4-5-20251001-v1:0", "endpoint": "runtime", "effort": "", "price_input_per_mtok": 1, "price_output_per_mtok": 5}`), so CI deploys use the same model as `config.local.yaml`. For a custom domain, also `DOMAIN_NAME`.
   - **Secrets:** `AWS_ACCOUNT_ID` and `ALERT_EMAIL` (the budget alert address), plus `CERTIFICATE_ARN` for a custom domain. Secrets are masked in Actions logs, which are public on a public repo.
   - **Environments:** create `production`. If anyone else can push to main, add yourself as a required reviewer so deploys wait for your approval.
4. Run **Refresh content** once from the Actions tab to confirm access.

The deploy workflow rebuilds `config.local.yaml` from those settings, so change other deploy settings in `config.example.yaml`.
