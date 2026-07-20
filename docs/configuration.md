# Configuration

prbot is configured via environment variables with the `PR_BOT_` prefix. Copy `.env.example` to `.env` to get started:

```sh
cp .env.example .env
```

## Environment variables

### Required

| Variable                         | Description                          |
| -------------------------------- | ------------------------------------ |
| `PR_BOT_GITHUB_APP_ID`          | GitHub App ID                        |
| `PR_BOT_GITHUB_PRIVATE_KEY`     | GitHub App private key (PEM format)  |
| `PR_BOT_GITHUB_WEBHOOK_SECRET`  | Secret for verifying GitHub webhooks |

### Slack (optional)

Setting these enables the Slack integration. If omitted, prbot starts without Slack support.

| Variable                         | Description                         |
| -------------------------------- | ----------------------------------- |
| `PR_BOT_SLACK__BOT_TOKEN`       | Slack bot OAuth token (`xoxb-...`)  |
| `PR_BOT_SLACK__SIGNING_SECRET`  | Slack app signing secret            |

### Discord (optional)

Setting this enables the Discord integration. If omitted, prbot starts without Discord support.

| Variable                         | Description                         |
| -------------------------------- | ----------------------------------- |
| `PR_BOT_DISCORD__BOT_TOKEN`     | Discord bot token                   |

!!! info "Nested config"
    The double underscore (`__`) is the nested delimiter. `PR_BOT_SLACK__BOT_TOKEN` maps to `settings.slack.bot_token` and `PR_BOT_DISCORD__BOT_TOKEN` maps to `settings.discord.bot_token` internally.

### Server

| Variable              | Default          | Description                |
| --------------------- | ---------------- | -------------------------- |
| `PR_BOT_HOST`         | `0.0.0.0`       | Server bind address        |
| `PR_BOT_PORT`         | `8080`           | Server port                |
| `PR_BOT_DATABASE_PATH`| `data/pr_bot.db` | Path to SQLite database    |

## Custom emoji

### Emoji pack setup

prbot ships with custom emoji images in the [`docs/images/emojis/`](images/emojis/) directory that match the default configuration. These need to be uploaded to your Slack workspace or Discord server before the bot can use them.

A helper script is included to automate this:

=== "Slack"

    Requires an admin-level user token (`xoxp-...`) with the `admin.emoji:write` scope.

    ```sh
    uv run python scripts/upload_emojis.py slack --token xoxp-your-admin-token
    ```

=== "Discord"

    Requires a bot token with the **Manage Guild Expressions** permission.

    ```sh
    uv run python scripts/upload_emojis.py discord --token YOUR_BOT_TOKEN --guild-id 123456789
    ```

The script uploads each image from `emojis/` using the filename (without extension) as the emoji name. Emoji that already exist are skipped.

| Emoji | Name | Used for |
| :---: | ---- | -------- |
| ![git-merged](images/emojis/git-merged.png){: style="height:24px"} | `:git-merged:` | Merged PRs |
| ![git-approved](images/emojis/git-approved.png){: style="height:24px"} | `:git-approved:` | Approved PRs |
| ![git-changes-requested](images/emojis/git-changes-requested.png){: style="height:24px"} | `:git-changes-requested:` | PRs with changes requested |
| ![speech_balloon](images/emojis/speech_balloon.png){: style="height:24px"} | `:speech_balloon:` | PRs with only comments |
| 🪦 | `:headstone:` | Closed PRs (native Unicode, no upload needed) |
| ❌ | `:ci_failed:` | PRs with failing CI (custom; falls back to `:x:` / ❌ if not uploaded) |

### Overriding defaults

Override the default emoji reactions by setting environment variables with the `PR_BOT_EMOJI__` prefix.

| Variable                             | Default                    |
| ------------------------------------ | -------------------------- |
| `PR_BOT_EMOJI__APPROVED`            | `git-approved`             |
| `PR_BOT_EMOJI__CHANGES_REQUESTED`   | `git-changes-requested`    |
| `PR_BOT_EMOJI__COMMENTED`           | `speech_balloon`           |
| `PR_BOT_EMOJI__MERGED`              | `git-merged`               |
| `PR_BOT_EMOJI__CLOSED`              | `headstone`                |
| `PR_BOT_EMOJI__CI_FAILED`           | `ci_failed`                |

Open PRs with no reviews receive no emoji reaction.

The CI-failure emoji is added when any check run on the PR's head commit fails. Subscribing the GitHub App to the **Check suites** event is required — see [GitHub Integration](integrations/github.md).

Values can be either:

- **Custom emoji names** (ASCII, no colons) — e.g. `shipit`, `git-merged`. These must be uploaded to your Slack workspace or Discord server.
- **Unicode emoji** (literal characters) — e.g. `🪦`, `🚀`. These work natively on both platforms without any upload.

For example, to use a custom `:shipit:` emoji for approved PRs:

```sh
PR_BOT_EMOJI__APPROVED=shipit
```

Or to use a native Unicode emoji for closed PRs:

```sh
PR_BOT_EMOJI__CLOSED=🪦
```

!!! note "Platform differences"
    Slack resolves emoji by name for both custom and native Unicode emoji. Discord requires the literal Unicode character for native emoji, which prbot handles automatically — custom emoji names are looked up in the server's emoji list, and Unicode characters are passed through directly.

## Scoped emoji overrides

Beyond the global defaults, prbot supports **per-workspace and per-channel** emoji overrides via the `scope_configs` database table. This lets different teams or channels use different emoji without changing the global config.

### How scope resolution works

When a PR link is detected, prbot builds a list of **scope keys** from most-specific to least-specific and returns the first match. If no scope matches, the global default is used.

=== "Slack"

    | Priority | Scope key format                     | Example                         |
    | -------- | ------------------------------------ | ------------------------------- |
    | 1        | `slack/<team_id>/<channel_id>`       | `slack/T123ABC/C456DEF`         |
    | 2        | `slack/<team_id>`                    | `slack/T123ABC`                 |
    | 3        | `slack`                              | `slack`                         |

=== "Discord"

    | Priority | Scope key format                     | Example                         |
    | -------- | ------------------------------------ | ------------------------------- |
    | 1        | `discord/<guild_id>/<channel_id>`    | `discord/111222333/444555666`   |
    | 2        | `discord/<guild_id>`                 | `discord/111222333`             |
    | 3        | `discord`                            | `discord`                       |

### Setting a scope override

Insert a row into the `scope_configs` table. Only the emoji you specify are overridden — any omitted fields fall back to the global defaults.

```sql
INSERT INTO scope_configs (scope_key, emoji_config)
VALUES ('slack/T123ABC/C456DEF', '{"approved": "shipit", "merged": "rocket"}');
```

!!! tip "Finding your IDs"
    - **Slack**: right-click a channel > "Copy link" to find the channel ID, or check workspace settings for the team ID
    - **Discord**: enable Developer Mode in Discord settings, then right-click guilds/channels to copy IDs

## User exclusions

You can exclude specific GitHub usernames from triggering PR status emoji updates. This is useful for bot accounts like `Cursor`, `dependabot[bot]`, or CI users whose activity would create noise.

Exclusions are managed per-scope via the `/prbot` slash command in Slack or Discord (see [Commands](commands.md) for the full reference).

### Quick start

```
/prbot exclusions add Cursor                # exclude in this channel
/prbot exclusions add Cursor workspace      # exclude across the entire workspace
/prbot exclusions add dependabot[bot]
```

### How exclusion scoping works

Like emoji overrides, exclusions are attached to a **scope key**. When a GitHub webhook fires, prbot checks the exclusion list for each scope that a tracked message belongs to.

```mermaid
flowchart LR
    WH["GitHub webhook<br/>(sender: Cursor)"] --> CHECK{"Is sender excluded<br/>in any matching scope?"}
    CHECK -->|Yes| SKIP[Skip — no emoji added]
    CHECK -->|No| REACT[Resolve emoji + react]
```

Commands accept an optional scope level (`channel` or `workspace`) as a second argument. If omitted, they default to the current channel.

=== "Slack"

    | Command | Scope key stored | Effect |
    | ------- | ---------------- | ------ |
    | `/prbot exclusions add Cursor` | `slack/T123ABC/C456DEF` | Excluded only in this channel |
    | `/prbot exclusions add Cursor workspace` | `slack/T123ABC` | Excluded in all channels |

=== "Discord"

    | Command | Scope key stored | Effect |
    | ------- | ---------------- | ------ |
    | `/prbot exclusions add Cursor` | `discord/111222333/444555666` | Excluded only in this channel |
    | `/prbot exclusions add Cursor workspace` | `discord/111222333` | Excluded in all channels |

    This excludes the user in **all channels** within that guild, since prbot walks from most-specific to least-specific scope when checking exclusions.

### Data model

Exclusions are stored in their own table, separate from emoji config:

| Table | Columns | Purpose |
| ----- | ------- | ------- |
| `scope_configs` | `scope_key`, `emoji_config` | Per-scope emoji overrides |
| `user_exclusions` | `scope_key`, `username` | Per-scope user exclusions |

Each config domain owns its own storage. The scope key is the shared concept that ties them together.

## Example `.env` file

```sh
# GitHub App (required)
PR_BOT_GITHUB_APP_ID=123456
PR_BOT_GITHUB_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"
PR_BOT_GITHUB_WEBHOOK_SECRET=super-secret-value

# Slack integration (optional — omit to disable)
PR_BOT_SLACK__BOT_TOKEN=xoxb-your-bot-token
PR_BOT_SLACK__SIGNING_SECRET=your-slack-signing-secret

# Discord integration (optional — omit to disable)
PR_BOT_DISCORD__BOT_TOKEN=your-discord-bot-token

# Server (optional — defaults shown)
PR_BOT_HOST=0.0.0.0
PR_BOT_PORT=8080
PR_BOT_DATABASE_PATH=data/pr_bot.db

# Custom emoji (optional — uncomment to override defaults)
# PR_BOT_EMOJI__MERGED=git-merged
# PR_BOT_EMOJI__APPROVED=git-approved
```
