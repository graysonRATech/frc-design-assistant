# FRC Design RAG Agent

A cited Q&A assistant for FRC **design, CAD (Onshape) and fabrication** questions, built for a team's students to use during the season. Answers come from a curated knowledge base, and every answer links back to its source.

Architecture, costs and decisions are in [docs/discovery.md](docs/discovery.md).

## Status

| Phase | What | State |
|---|---|---|
| 1 | Ingestion: `sources.yaml` → normalized, chunked Markdown + metadata | ✅ |
| 2 | AWS stack (CDK): S3, Bedrock Knowledge Base on S3 Vectors, chat Lambda, audit log, budget guardrails | ✅ deployed; content load awaits Bedrock quotas |
| 3 | Student web UI, API Gateway, Google sign-in via Cognito, allowlist, feedback | ✅ deployed |
| 4 | GitHub Actions: tests, source previews on PRs, deploys, daily content refresh | ✅ built; needs a GitHub repo |
| 5 | Onshape: chat panel beside the CAD | ✅ built |

## Knowledge sources

Sources live in [`sources.yaml`](sources.yaml). To add a website or repository, append an entry and open a pull request. The file header documents every field. The pull request runs the real ingestion and shows the document and chunk counts in its checks; once merged, the content workflow loads it into the knowledge base.

| Source | Content | Credit |
|---|---|---|
| [FRCDesign.org](https://www.frcdesign.org/) | Learning course, design handbook, mechanism examples, best practices | FRCDesign.org contributors, ingested from [frcdesign/FRCDesign.org](https://github.com/frcdesign/FRCDesign.org) |
| [FRC Game Manual](https://www.firstinspires.org/resources/library/frc/season-materials) | The current season's rules, one document per rule, plus field, scoring and tournament sections | *FIRST*, from the official HTML edition |
| [Past FRC games](https://www.firstinspires.org/resources/library/frc/archived-games) | 2018–2025 games (2021 excepted): overview, field and match chapters, for comparing a new game with old ones | *FIRST*, from the archived PDF manuals |

Answers always cite and link to the original page. Content stays with its authors.

### Game manual

Each rule (R103, G204, ...) is its own document, titled like "2026 Game Manual R103: ROBOT weight limit" and linked straight to that rule in FIRST's HTML manual. Answers name the rule number, quote the deciding words, and say which season they're from. The rest of the manual (field, scoring, tournaments, glossary) is split by numbered section.

- **Team Updates:** FIRST republishes the HTML manual at the same address with each revision. The content refresh runs daily, so the new wording is in answers by the next morning.
- **Kickoff day:** with `next_season: true` the ingester looks for next season's manual first, so the daily refresh switches to the new game by itself the morning after kickoff. To switch the same day, run **Refresh content** from the Actions tab once FIRST has posted the manual. Afterwards, set `year` in `sources.yaml` to the new season, and update the rule numbers in the game-manual cases in `evals/retrieval.yaml`.
- **Past games:** for kickoff day, the overview, field and match chapters of past manuals are loaded too, titled "Past game: 2022 RAPID REACT, 5.3 Hub", so students can ask what the new game shares with old ones. Their rules chapters are left out, so an old rule is never cited as current. Each game also has a short hand-written summary in `sources.yaml` (game pieces with sizes, goals, endgame), loaded as "at a glance" documents plus one list of every game, so questions across seasons ("which games had a central hub?") find all of them at once.
- **After kickoff:** add the season that just ended to `past-games` in `sources.yaml`: its PDF, chapter numbers and a summary written from its overview and game piece sections.
- **Not yet included:** the official Q&A system ([#2](https://github.com/graysonRATech/frc-design-assistant/issues/2)). FIRST's Q&A answers clarify rules but aren't part of the manual.

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
| Chat Lambda (`backend/chat_api`) | Retrieves the top 6 chunks, asks Claude (set in `model`), returns the answer with cited sources. Also serves saved chats |
| Chat stream function (`chat_api/server.py`) | Same pipeline, streamed to the page through a Lambda function URL (API Gateway can't stream). Python Lambdas can't stream on their own, so it runs behind the AWS [Lambda Web Adapter](https://github.com/awslabs/aws-lambda-web-adapter) layer and checks the Cognito ID token itself. Shares the chat Lambda's role, so the Budgets kill switch covers it |
| DynamoDB table | Audit log (question, answer, sources, tokens and cost per request; 365-day TTL), spend counters, and saved chats (deleted `chat_retention_days` after their last message, or by the student) |
| AWS Budgets | Email at 50/80/100% of the monthly budget and on forecast; at 120% an IAM deny on all Bedrock calls |
| Monitoring | An alarm that emails `alert_email` when any answering function (chat, web stream, Slack) logs an error, and again when it clears; a daily 12:00 UTC test question through the streaming pipeline (about half a cent). Confirm the "AWS Notification - Subscription Confirmation" email once after the first deploy |
| Cognito user pool | Google sign-in only. Allowlist triggers (`backend/auth_triggers`) reject anyone not added with `kb users add`, on sign-up and on every token refresh |
| HTTP API | `POST /chat`, `POST /feedback`, the mentor review routes (`/review`) and the saved-chat routes (`/chats`), all behind a Cognito JWT authorizer; throttled to 5 req/s |
| CloudFront + S3 | The chat page (`web/`: React + [Astryx](https://github.com/meta/astryx), built with Vite) under a strict Content-Security-Policy. Saved chats, streamed answers with Stop, copy, retry and edit, and a per-user theme (Auto, Forge, Collegiate, Blueprint) saved with `GET`/`PUT /settings` |
| Slack bot (`chat_api/slack.py`, optional) | A receiver behind a public function URL checks Slack's request signature and hands each question to a worker, which streams the answer into a Slack thread. Same allowlist, daily limits and audit log as the web page; the worker shares the chat role. Deployed only when `slack.team_id` is set |

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

The allowlist is stored in DynamoDB, never in this repository. Feedback from the 👍/👎 buttons is stored next to the audit log (`pk = FEEDBACK`), with a copy of the question, answer and sources it rates.

### Reviewing feedback

Mentors and admins get **Review feedback** in the account menu (or go to `/#review`). It lists the answers students marked not helpful, newest first: the student's comment, the question, the answer as they saw it, its sources, and everything search retrieved, with scores. That last part shows whether a bad answer came from search missing the right page or from the model misreading it. Mark an item reviewed, with an optional note such as "added eval case", and it leaves the to-review list. **Copy as test case** gives a starting point for [`evals/answers.yaml`](evals/answers.yaml), so a fixed problem stays fixed. Students get a 403 from `/review`; the role check is in the chat Lambda.

### Answer quality

`kb eval` checks retrieval: did search find the right page? `uv run --group aws kb answers` checks what students actually see. It asks the deployed assistant each question in [`evals/answers.yaml`](evals/answers.yaml) through the same streaming pipeline as the website and Slack, then grades each answer:

- **Fixed checks (free):** the right source is cited, required facts appear (`include`), and known-wrong claims don't (`exclude`).
- **Rubric:** for what a pattern can't judge ("doesn't name teams as best without a source"), Claude grades each criterion yes or no. By default it uses the assistant's own model.

Cases cover design, CAD, the game rules, past games, honesty about what the references don't cover, safety, and off-topic or prompt-injection questions. A run costs about a cent per case and pauses between cases so it doesn't take Bedrock quota from students. It prints pass rates per area and saves a JSON report with every answer to `build/evals/`.

Run it before and after changing the model, the prompt or the sources, and compare the reports. When students hit a bad answer, add it as a case. `--only rules` runs one area, `--only robot-weight` one case.

### Costs

At idle the stack costs about $0.40/month: the Google client secret in Secrets Manager. S3 Vectors, DynamoDB on-demand, Lambda, API Gateway, CloudFront and Cognito (Lite, under 10,000 monthly users) all bill per use or fall under free tiers, and the first two budgets are free. A question costs about $0.01–0.015, mostly Claude tokens: roughly 3.5k input and 500 output tokens. The app caps (`limits` in the config) stop spending before AWS Budgets has to.

If the Budgets kill switch fires, detach the `BudgetDenyBedrock` policy from the two roles in IAM to restore service, after raising the budget.

### Tests

```sh
uv run --group infra --group aws pytest    # includes CDK template assertions (~20 s)
```

### Working on the chat page

`cdk deploy` builds the page (`scripts/build_web.py`: `npm ci`, then `npm run build`), so Node.js 22+ is
needed for deploys. To work on it locally:

```
cd web
npm ci
curl -s https://frc.ratech.ai/config.json -o public/config.json   # point the page at the deployed API (gitignored)
npm run dev
```

Sign-in redirects back to the deployed site, so add `http://localhost:5173` to `web.extra_origins` and
deploy once before signing in locally. The three TORCH themes live in `web/src/themes/*.mjs` and are
compiled to static CSS by `npm run themes` (Astryx `theme build`), so no styles are injected at runtime
and the Content-Security-Policy stays strict. `npm run preview` serves the build with that same policy.

The flame-in-gear mark in `web/src/components/Brand.jsx` and `web/public/favicon.svg` is a placeholder
until the team's official logo file is added.

### Custom domain

The site works at its CloudFront address out of the box. To serve it from your own name, such as `frc.example.org`:

1. Request a certificate in **us-east-1** (CloudFront only uses certificates from there):
   `aws acm request-certificate --region us-east-1 --domain-name frc.example.org --validation-method DNS`
2. Add the validation CNAME that `aws acm describe-certificate` shows at your DNS provider, and wait for the status `ISSUED`.
3. Set `web.domain_name` and `web.certificate_arn` in `config.local.yaml` and deploy.
4. Point the name at the `WebUrl` CloudFront host with a CNAME. On Cloudflare, set the record to **DNS only** (grey cloud): CloudFront already serves HTTPS, and proxying through Cloudflare breaks it.

The CloudFront address keeps working for sign-in, so old links don't break. Google needs no changes.

### Slack bot

Students mention **@TORCH** in a channel (after inviting it there), or DM it, and the answer streams into a thread with its sources. Follow-ups in the same thread keep the conversation going; stopping the answer in Slack stops it generating. The bot only sees messages that mention it or are sent to it directly.

Who gets answers: full members of your workspace whose Slack profile email is on the access list (an email entry, or a domain entry like `@collegiate-va.org`). Guests, people from other workspaces in shared channels, and anyone not on the list get a private "not on the access list" reply. Slack questions count toward the same daily limit as the website.

Setup (you need to be a workspace admin, or have one approve the app):

1. At [api.slack.com/apps](https://api.slack.com/apps), choose **Create New App > From a manifest**, pick the workspace, and paste [`slack/manifest.yaml`](slack/manifest.yaml).
2. **Install to Workspace**. Note the **Bot User OAuth Token** (OAuth & Permissions, starts `xoxb-`) and the **Signing Secret** (Basic Information). Find the workspace ID (starts with `T`) under your workspace's **About** page or in the URL of Slack in a browser.
3. In the AWS console, create a Secrets Manager secret named `frcrag/slack` (type "Other", key/value) with keys `bot_token` and `signing_secret`. Don't paste them into chat, files or the terminal.
4. Set `slack.team_id` in `config.local.yaml` (and the `SLACK_TEAM_ID` repository variable for GitHub deploys), then deploy. The stack prints `SlackEventsUrl`.
5. Back in the Slack app: **Event Subscriptions > Enable Events**, paste `SlackEventsUrl` as the Request URL (it should show **Verified**), add the bot events `app_mention` and `message.im`, and save. Reinstall the app if Slack asks.

Each thread is stored under `SLACK#<channel>` and deleted `chat_retention_days` after its last message.

### Onshape panel

The chat also runs in a panel on the right side of Onshape, next to the CAD, at `https://<site>/onshape/index.html`. It's the same app, signed in with the same Google account, with the same access list and limits. It makes no Onshape API calls, so it doesn't use the plan's yearly API allowance.

- **Framing:** CloudFront lets only that path be framed, and only by `cad.onshape.com` (and `*.onshape.com`). Every other page still refuses to be framed.
- **Sign-in:** Google won't show its sign-in page inside another site's frame, so **Sign in with Google** in the panel opens a small popup. The popup returns an authorization code by `postMessage`. If Google's pages cut the popup off from the panel, a small handoff endpoint (`backend/chat_api/handoff.py`) holds the code for at most 5 minutes and gives it out once. The code is useless without the PKCE verifier, which never leaves the panel.
- **Storage:** the panel keeps its own sign-in, since browsers keep an embedded site's storage separate from the main site's. Students sign in once in Onshape. Browsers that block embedded storage keep it until the tab closes.

Setup (Classroom or company admin, once):

1. In Onshape, go to **Classroom settings > Developer > OAuth applications** and click **Create new OAuth application**. Use any name (e.g. "TORCH Design Assistant") and a primary format like `org.torch5804.design`. Set the redirect URL to `https://<site>/onshape/index.html`. Grant no permissions: the panel doesn't call Onshape's API. Creating it under Classroom settings makes the team the owner, not one person.
2. On the app's **Extensions** tab, click **Add extension**:
   - **Location:** Element right panel. **Context:** Part Studio (add a second extension for Assembly if you want it there too).
   - **Action URL:** `https://<site>/onshape/index.html?documentId={$documentId}&workspaceOrVersion={$workspaceOrVersion}&workspaceId={$workspaceOrVersionId}&elementId={$elementId}`
   - **Icon:** the TORCH logo (`web/public/favicon.svg`, exported as PNG if Onshape asks).
3. On the app's **Users** (or access) settings, assign the team: individual users, an alias, or a team.
4. Open a Part Studio. The panel's icon appears in the right-hand toolbar.

## Continuous deployment

Four workflows in [`.github/workflows`](.github/workflows), with actions pinned to commit SHAs:

| Workflow | Runs on | Does | AWS access |
|---|---|---|---|
| CI | every PR and push | tests, `sources.yaml` check, `cdk synth` | none |
| Preview sources | PRs touching sources or the ingester | real `kb ingest`, counts in the job summary | none |
| Deploy | push to main touching infra/backend/web; manual | tests, then `cdk deploy` | `FrcRag-github-deploy` |
| Refresh content | daily, merges touching sources; manual | `kb ingest`, `kb sync`, `kb eval` | `FrcRag-github-content` |

After each deploy, the Deploy workflow runs [`scripts/smoke_test.py`](scripts/smoke_test.py): the chat page loads, the streaming URL refuses unsigned requests, and one real question is answered with cited sources through the same role and Bedrock calls students use. A failure fails the run. You can run it yourself with AWS credentials: `uv run python scripts/smoke_test.py`.

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
