# GitHub

This guide walks you through creating a GitHub App and configuring webhooks so prbot can fetch PR status and receive real-time updates.

## Step 1: Create a GitHub App

1. Go to **Settings > Developer settings > GitHub Apps** in your GitHub account (or organisation)
2. Click **New GitHub App**
3. Fill in the details:

| Field                  | Value                                         |
| ---------------------- | --------------------------------------------- |
| **App name**           | `prbot` (or any name you like)                |
| **Homepage URL**       | Your repository or docs URL                   |
| **Webhook URL**        | `https://your-domain.com/github/webhooks`     |
| **Webhook secret**     | A strong random string (save it for later)    |

!!! tip "Generating a webhook secret"
    ```sh
    openssl rand -hex 32
    ```

## Step 2: Set permissions

Under **Permissions & events**, configure:

### Repository permissions

| Permission       | Access    | Purpose                              |
| ---------------- | --------- | ------------------------------------ |
| **Pull requests**| Read-only | Fetch PR status & reviews            |
| **Checks**       | Read-only | Fetch CI/check-run state             |
| **Metadata**     | Read-only | Required by GitHub                   |

!!! note "Checks permission is optional"
    The **Checks** permission and **Check suites** subscription below are only
    needed for the CI-failure emoji (❌). Omit them and prbot still works — it
    just won't react to CI failures.

### Event subscriptions

Subscribe to these events:

| Event                    | Purpose                                      |
| ------------------------ | -------------------------------------------- |
| **Pull request**         | Notified when PRs are opened, closed, merged |
| **Pull request review**  | Notified when reviews are submitted          |
| **Check suite**          | Notified when CI completes                   |

!!! tip "Grant Checks before subscribing to Check suite"
    **Check suite** only becomes tickable once **Checks** is set to Read-only —
    GitHub restricts event subscriptions to permissions you already hold.

## Step 3: Generate a private key

1. After creating the app, scroll to **Private keys**
2. Click **Generate a private key**
3. A `.pem` file will download — keep this safe

## Step 4: Note the App ID

On the app's **General** page, copy the **App ID** (a numeric value).

## Step 5: Install the app

1. Go to **Install App** in the sidebar
2. Click **Install** on your account or organisation
3. Choose which repositories the app can access:
    - **All repositories** — prbot can track PRs in any repo
    - **Only select repositories** — pick specific repos

## Step 6: Configure prbot

Add the following to your `.env` file:

```sh
PR_BOT_GITHUB_APP_ID=123456
PR_BOT_GITHUB_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"
PR_BOT_GITHUB_WEBHOOK_SECRET=your-webhook-secret
```

!!! warning "Private key formatting"
    When setting the private key as an environment variable, you can either:

    - Use the entire PEM content with `\n` for newlines (as shown above)
    - Set it as a multi-line value in your `.env` file using quotes

    In production (e.g. Fly.io), set the secret via the platform's secrets management.

## Enabling the CI-failure emoji on an existing app

The **Checks** permission and **Check suite** subscription (Step 2) power the
❌ CI-failure emoji. If you add them to an app that was **already installed**,
two extra steps are needed:

1. **Approve the updated permissions.** Go to
   **[github.com/settings/installations](https://github.com/settings/installations)**
   → **Configure** → accept the request. Permission changes are not applied to
   existing installations until approved — until then the token lacks Checks
   access and you'll see `403 Forbidden` on check-runs in the logs. (Org installs
   need an owner to approve.)
2. **Restart prbot.** Past `check_suite` webhooks are never redelivered, so a
   restart is what lets startup reconciliation catch failures that already
   happened.

!!! tip "Verifying delivery"
    The app's **Advanced** tab lists **Recent Deliveries**. After setup you
    should see `check_suite` deliveries returning `200`; use **Redeliver** to
    re-trigger one without waiting for a fresh CI run.

## How authentication works

prbot uses the **GitHub App installation token** flow:

```mermaid
sequenceDiagram
    participant prbot
    participant GitHub

    prbot->>prbot: Generate JWT (signed with private key)
    prbot->>GitHub: GET /orgs/{owner}/installation
    GitHub-->>prbot: Installation ID
    prbot->>GitHub: POST /app/installations/{id}/access_tokens
    GitHub-->>prbot: Installation token (1hr TTL)
    prbot->>GitHub: GET /repos/{owner}/{repo}/pulls/{number}
    Note over prbot: Tokens are cached until expiry
```

This means:

- No personal access tokens needed
- Tokens are scoped to the installed repositories
- Tokens auto-expire after 1 hour and are refreshed automatically
