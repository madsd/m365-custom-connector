# Tenant configuration & validation guide

This guide walks you through deploying the PubMed MCP server and wiring it up as a
**custom federated connector** in your Microsoft Entra / Microsoft 365 tenant, secured
with **Microsoft Entra single sign-on (SSO)**. It ends with concrete validation steps.

> Reference: [Set up custom federated connectors](https://learn.microsoft.com/en-us/microsoft-365/copilot/connectors/set-up-custom-federated-connectors)
> and [Configure authentication for MCP and API plugins](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/plugin-authentication).

---

## How the pieces fit together

There is a deliberate ordering because three identifiers depend on each other:

1. You deploy the server first to get its **public URL** (FQDN).
2. The **Teams Developer Portal** SSO registration needs that URL + your Entra **client ID**,
   and in return generates an **SSO registration ID** and an **Application ID URI**.
3. Your **Entra app registration** must then trust that Application ID URI, and your **server**
   must accept it as the token audience.
4. Finally, the **Microsoft 365 admin center** connector ties the public URL to the SSO
   registration ID.

Because of this, the server is deployed **twice**: once unauthenticated (to get the URL), then
again locked down once you know the audience.

---

## Prerequisites

- **Azure**: a subscription where you can create resources, plus the
  [Azure Developer CLI (`azd`)](https://aka.ms/azd) and Docker installed.
- **Roles**:
    - **Global Administrator** or **AI Administrator** in the [Microsoft 365 admin center](https://admin.microsoft.com/).
    - **Application Administrator** (or equivalent) in [Microsoft Entra](https://entra.microsoft.com/) to manage app registrations.
- Access to the [Teams Developer Portal](https://dev.teams.microsoft.com/).
- Your **Microsoft Entra tenant ID** (Entra admin center → **Overview**).

> Note: changes to a connector can take up to **15 minutes** to take effect.

---

## Part A — Deploy the MCP server (first pass, unauthenticated)

This gets you a stable public HTTPS URL.

```powershell
cd m365-custom-connector

azd auth login
azd env new pubmed-connector

# First pass: no auth so we can obtain the URL and confirm it works.
azd env set AUTH_REQUIRED false
azd env set NCBI_EMAIL "you@example.com"     # optional but recommended by NCBI
# azd env set NCBI_API_KEY "<key>"           # optional, higher rate limits

azd up
```

`azd` provisions Azure Container Registry, a Container Apps environment, and the container
app, then builds and deploys the image. When it finishes, note the output:

```javascript
SERVICE_MCP_URI       https://ca-mcp-xxxx.<region>.azurecontainerapps.io
SERVICE_MCP_ENDPOINT  https://ca-mcp-xxxx.<region>.azurecontainerapps.io/mcp
```

**Record these two values.** The `/mcp` endpoint is your connector **Base URL**.

Confirm it's live:

```powershell
curl https://ca-mcp-xxxx.<region>.azurecontainerapps.io/health
# -> {"status":"ok"}
```

---

## Part B — Create the Microsoft Entra app registration

This app registration represents (secures) your MCP server.

1. Open [Microsoft Entra admin center](https://entra.microsoft.com/) → **Identity** →
   **Applications** → **App registrations** → **New registration**.
2. **Name**: `PubMed MCP Connector`.
3. **Supported account types**: \*Accounts in any organizational directory (Any Microsoft Entra ID
   tenant — Multitenant)\*. **This is required** — the Microsoft 365 Copilot connector validation
   rejects single-tenant app registrations with the error \*"not configured as a multi-tenant
   application"\*. (You can switch an existing app later under \*\*Authentication → Supported account
   types → Accounts in any organizational directory\*\*.)
4. Leave **Redirect URI** empty for now. Select **Register**.
5. On the **Overview** page, copy the **Application (client) ID** — you'll need it in Part C.
6. Go to **Expose an API**:

Next to **Application ID URI**, select **Add**. Accept the default `api://<client-id>`
     and **Save**. (The Teams Developer Portal will generate an *additional* URI in Part C;
     this default just initializes the section.)Select **Add a scope**. Create a scope so the API is consent-able:**Scope name**: `access_as_user`**Who can consent**: *Admins and users***Admin consent display name / description**: `Access PubMed MCP`**State**: *Enabled* → **Add scope**.

Leave this tab open; you'll return in Part D.

---

## Part C — Register the Entra SSO client in the Teams Developer Portal

1. Open the [Teams Developer Portal](https://dev.teams.microsoft.com/tools) → **Tools** →
   **Microsoft Entra SSO client ID registration**.
2. Select **Register client ID** (or **New client registration**).
3. Fill in:

**Registration name**: `PubMed MCP Connector`.**Base URL**: your MCP endpoint \*\*including `/mcp`\*\*, e.g.
     `https://ca-mcp-xxxx.<region>.azurecontainerapps.io/mcp`.**Restrict usage by org**: select your tenant/organization.**Restrict usage by app**: choose **Any Teams app** (you can bind a specific app later).**Client ID**: the **Application (client) ID** from Part B.

4. Select **Save**.
5. The portal now displays two values — **copy both**:

**Microsoft Entra SSO registration ID** → used in Part F.**Application ID URI** (e.g. `api://<fqdn>/<client-id>`) → used in Parts D and E as the
     **token audience**.

> **⚠️ Critical — leave the SSO registration's scope field EMPTY.** Do not add a scope
> value (such as `access_as_user`) to the Teams Dev Portal SSO registration. If a literal
> scope is stored here, the M365 admin center passes it **verbatim** as a *bare* scope, which
> Azure AD resolves against Microsoft Graph and rejects with **AADSTS650053**
> (*"…asked for scope 'access_as_user' that doesn't exist on the resource '00000003-0000-…'"*).
> With the field empty, the admin center auto-qualifies the request to
> `<client-id>/.default`, which is what you want. If you already added one, remove it and
> recreate the connector.

---

## Part D — Finalize the Entra app registration

Back in the Entra app registration from Part B:

1. **Expose an API → Application ID URI**: add the **Application ID URI generated in Part C**.

In the Entra portal UI, use **App registrations → (your app) → Manifest** (or the
     **Expose an API** edit dialog). The portal UI only shows the first URI, but adding more
     does not remove existing ones. You want **both** `api://<client-id>` and the generated
     `api://<fqdn>/<client-id>` present in `identifierUris`.

2. **Authentication → Add a platform → Web**: add this **Redirect URI**:

```javascript
   https://teams.microsoft.com/api/platform/v1.0/oAuthConsentRedirect
```

   Select **Configure / Save**.

3. **Expose an API → Authorized client applications → Add a client application**: add the
   **Microsoft enterprise token store** client ID and check your `access_as_user` scope:

```javascript
   ab3be6b7-f5df-413d-ac2d-abf1e3fd9c0b
```

   Select **Add application**.

This makes Copilot's token store a trusted caller and ensures tokens it requests carry your
Application ID URI as the audience.

---

## Part E — Lock down the server (second deploy, authenticated)

Now that you know the audience, enable authentication and redeploy.

```powershell
azd env set ENTRA_TENANT_ID "<your-tenant-id>"
# IMPORTANT: include ALL THREE audience forms, comma-separated. The admin center's SSO flow
# requests the "<client-id>/.default" scope, which yields a v2 token whose `aud` is the bare
# client-id GUID — NOT the api://auth-… URI. List every form so validation matches:
azd env set ENTRA_AUDIENCE "api://<fqdn>/<client-id>,api://<client-id>,<client-id>"
azd env set AUTH_REQUIRED true

azd up
```

> **⚠️ Critical — audience must include the client-id GUID.** A common failure is a **401 on
> the connector's "Authorize" / test-authentication step** with the server logging
> *"rejected: Audience doesn't match"*. This happens when `ENTRA_AUDIENCE` only lists the
> `api://auth-…` URI but the `.default` token's `aud` is the plain client-id GUID. Listing all
> three forms above (the generated `api://<fqdn>/<client-id>` URI, `api://<client-id>`, and the
> bare `<client-id>` GUID) covers every token shape. The server splits `ENTRA_AUDIENCE` on
> commas and accepts a token matching any one of them.

Verify the lockdown — unauthenticated MCP calls must now be rejected while `/health` stays open:

```powershell
curl https://ca-mcp-xxxx.<region>.azurecontainerapps.io/health          # -> 200 {"status":"ok"}
curl -X POST https://ca-mcp-xxxx.<region>.azurecontainerapps.io/mcp -d "{}"   # -> 401 Unauthorized
```

---

## Part F — Create the connector in the Microsoft 365 admin center

1. Sign in to the [Microsoft 365 admin center](https://admin.microsoft.com/).
2. Left pane → **Copilot** → **Connectors**.
3. Select the **Gallery** tab.
4. Under **Created by your org**, find **Create a new connector** → **Add**.
5. On the **Custom connector** page, under **Connect to MCP server**, select **Add**.
6. Enter:

**Display name**: `PubMed`.**Base URL**: your MCP endpoint \*\*including `/mcp`\*\*, e.g.
     `https://ca-mcp-xxxx.<region>.azurecontainerapps.io/mcp`.

7. For the authentication method, choose **Microsoft Entra SSO** and enter the
   **SSO registration ID** from Part C.
8. Select **Save**.

---

## Part G — Roll out the connector

1. In **Copilot → Connectors → Your Connections**, select the **PubMed** connector.
2. (Recommended) **Staged rollout** → **Users** or **Groups** → add yourself / a test group.
3. When validated, select **Deploy to all users**.
4. Use **Enable / Disable / Delete** to manage its lifecycle.

> Allow up to **15 minutes** for changes to propagate.

---

## Part H — Validate

### 1. Validate the MCP server itself (transport + tools)

With **MCP Inspector** (no Copilot needed):

```powershell
npx @modelcontextprotocol/inspector
```

- Transport: **Streamable HTTP**
- URL: `https://ca-mcp-xxxx.<region>.azurecontainerapps.io/mcp`
- If auth is on, supply a bearer token (see token test below) in the Authorization header.
- Click **List Tools** → you should see `search` and `fetch`.
- Run `search` with `{ "query": "diabetes remission", "max_results": 3 }` → expect results
  with PMIDs, then `fetch` one of those PMIDs → expect an abstract.

Or use the included script against the deployed URL (works when `AUTH_REQUIRED=false`, or
locally):

```powershell
python scripts\smoke_test.py https://ca-mcp-xxxx.<region>.azurecontainerapps.io/mcp
```

### 2. Validate Entra SSO (token test)

Confirm the server accepts a properly-scoped token and rejects others.

```powershell
# Should fail with 401 (no token)
curl -i -X POST https://ca-mcp-xxxx.<region>.azurecontainerapps.io/mcp -d "{}"
```

To positively test a real token, acquire one for your API's scope (for example via the
Microsoft Graph PowerShell / MSAL or `az account get-access-token --resource api://<client-id>`
when signed in as a user who has consented) and call `/mcp` with
`Authorization: Bearer <token>`. A valid token returns an MCP response; a token with the wrong
audience or issuer returns **401**.

### 3. Validate end-to-end in Microsoft 365 Copilot

1. Open [Microsoft 365 Copilot](https://m365.cloud.microsoft/chat) as a user in the rollout group.
2. Ensure the **PubMed** connector is available (it may surface automatically, or via the
   connector/agent picker depending on tenant configuration).
3. Ask a question that requires live PubMed data, e.g.:
   > "Using PubMed, find recent studies on CRISPR gene editing for sickle cell disease and
   > summarize the key findings with citations."
4. Expect Copilot to:

Call the connector (`search` then `fetch`),Summarize results, andCite PubMed article links (`https://pubmed.ncbi.nlm.nih.gov/<pmid>/`).

5. Cross-check a cited PMID by opening its PubMed URL.

> **⚠️ Give it time to be picked up.** A newly published connector is **not** invoked
> immediately. Until Copilot's orchestrator indexes it into its tool catalog, the same prompt
> is answered by the **built-in web-search tool** instead — you'll see Copilot run
> `site:pubmed.ncbi.nlm.nih.gov …` web searches and cite public pages, and the Container App
> logs show **no** `CallToolRequest`. This is expected for the first ~15+ minutes after
> publish/rollout (it can occasionally take longer), **not** an auth or config fault. Once
> indexed, re-running the same query routes to your connector and the logs show
> `request of type CallToolRequest` → `POST /mcp 200 OK` with live `eutils.ncbi.nlm.nih.gov`
> calls. **The definitive validation signal is a `CallToolRequest` in the server logs**, since
> the connector may lack an M365 Copilot license to test in the UI.

---

## Troubleshooting

> ### ⚠️ Entra SSO "Authorize" popback can fail (COOP-severed opener) — and how it was resolved
> 
> **Status: RESOLVED.** The PubMed connector was successfully created and reached the **Ready** state,
> and M365 Copilot now calls the MCP server with a valid Entra token (the Container App logs show
> authenticated `POST /mcp → 200 OK` and a `ListToolsRequest` immediately after activation). The notes
> below explain a real handshake bug you may hit during **Authorize**, and the fix that worked.
> 
> **Symptom.** In the M365 admin center **Connect to MCP server** dialog, after you select
> **Entra SSO**, enter the **Reference ID**, and click **Authorize**, the consent pop-up opens and
> you can **Accept** (admin consent is recorded in Entra), but the dialog may then show
> \*"Authentication for connector was cancelled or closed before completion. Please restart the
> sign-in process…"\*. The **Create** button never enables and the connector stays in **Draft**.
> The consent tab's console shows *"Initialization Failed. No Parent window found."*
> 
> **Root cause (not a pop-up blocker).** The dialog opens the consent window directly to
> `https://login.microsoftonline.com/common/oauth2/v2.0/authorize?response_type=none&prompt=consent&…`.
> That response carries the header `Cross-Origin-Opener-Policy: same-origin`. COOP `same-origin` places
> the pop-up in a new browsing-context group and **sets `window.opener` to `null`** the instant the
> login page loads (verified directly). The flow then lands on Teams'
> `https://teams.microsoft.com/api/platform/v1.0/oAuthConsentRedirect`, whose
> `microsoftTeams…notifySuccess()` **requires `window.opener`** to post the result back to the admin
> center. With the opener severed, the success signal is never delivered, so the admin center reports
> "cancelled or closed." When this happens it is deterministic in plain Chromium/Edge — it is **not** a
> pop-up blocker and **not** a Reference-ID error.
> 
> **The fix that worked.** The handshake completes correctly as soon as the consent window keeps its
> `window.opener`. The reliable way to guarantee that is to \*\*strip the `Cross-Origin-Opener-Policy`
> response header from the `login.microsoftonline.com` (and `teams.microsoft.com`) document responses\*\*
> for the duration of the Authorize flow. We did this with a browser-automation response interceptor
> (Playwright `context.route` that deletes `cross-origin-opener-policy` on document responses); a local
> debugging proxy that rewrites the same header works equally well. With COOP removed:
> `window.opener` stayed intact → **Accept** (with *Consent on behalf of your organization*) →
> Teams `notifySuccess` posted back → **Create** enabled → connection moved \*\*Draft → PendingPublish →
> Ready\*\*. No server, Entra, or Teams change was needed — only the browser-side header strip.
> Once the connector is **Ready**, there is **no ongoing COOP dependency**: runtime token validation
> happens server-side and is unaffected.
> 
> **If you can't run an interceptor**, the supported fallback is a **Microsoft support ticket**
> (Microsoft 365 admin center → **Copilot connectors / Microsoft Search**) with this exact repro:
> \*"Custom federated connector, Entra SSO auth — the **Authorize** consent pop-up fails because
> `login.microsoftonline.com` returns `Cross-Origin-Opener-Policy: same-origin`, which nulls
> `window.opener` before Teams' `oAuthConsentRedirect` calls `notifySuccess`, so the connection can't
> leave Draft."\* Include the tenant ID, the `CustomULC…` connection ID, and a screenshot of the
> console *"No Parent window found"* error.
> 
> **Reference ID format (important).** For **Entra SSO** the **Reference ID** is
> `base64( "<tenantId>##<ssoRegistrationId>" )` — e.g.
> `base64("00000000-0000-0000-0000-000000000000##11111111-1111-1111-1111-111111111111")`. Entering the **raw GUID** is rejected
> with *"The request is malformed or incorrect."*

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Copilot answers with public/web PubMed pages and never calls the connector | (a) Connector not yet indexed by the orchestrator (propagation), or (b) not rolled out to the test user | Wait ~15+ min after publish/rollout and retry; confirm the connector is **Visible to everyone** (or the user is in the staged-rollout group). The proof of success is `request of type CallToolRequest` in the server logs — web searches with `site:pubmed.ncbi.nlm.nih.gov` mean it fell back to web search. |
| Copilot says it can't reach the connector | Base URL missing `/mcp`, or wrong FQDN | Re-check the **Base URL** in Part F. |
| `/mcp` returns 401 with a real user token | Audience mismatch | Set `ENTRA_AUDIENCE` to **all three** forms (`api://<fqdn>/<client-id>,api://<client-id>,<client-id>`) — the `.default` token's `aud` is the bare client-id GUID. Server log shows *"rejected: Audience doesn't match"*. See Part E callout. |
| Connector **"Authorize" / test-authentication** fails with **AADSTS650053** *"…scope 'access_as_user' that doesn't exist on the resource '00000003-0000-…'"* | A literal scope value is stored on the Teams Dev Portal SSO registration; the admin center passes it as a *bare* scope resolved against Microsoft Graph | **Remove** the scope value from the SSO registration so the admin center auto-qualifies to `<client-id>/.default`, then recreate the connector. See Part C callout. |
| Connector **"Authorize"** returns a **500** then a **400 (malformed)** on the draft, even after consent succeeds | Server rejected the test token (audience mismatch) so test-authentication 500s and **Create** never enables | Broaden `ENTRA_AUDIENCE` as above (Part E), confirm the new revision is live, then re-Authorize. |
| 401 mentioning "client application is not allowed" | Token store not authorized | Add `ab3be6b7-f5df-413d-ac2d-abf1e3fd9c0b` under **Expose an API → Authorized client applications** (Part D). |
| Tokens never issued / consent loop | Missing redirect URI | Add `https://teams.microsoft.com/api/platform/v1.0/oAuthConsentRedirect` to the **Web** platform (Part D). |
| Consent prompt appears, after **Accept** the dialog says *"Authentication for connector was cancelled or closed before completion"* and the connector stays **Draft**; consent tab console shows *"No Parent window found."* | The `login.microsoftonline.com` consent response sends `Cross-Origin-Opener-Policy: same-origin`, which nulls `window.opener` so Teams' `oAuthConsentRedirect` can't post the success back. Not a pop-up blocker. | See the **⚠️ Entra SSO "Authorize" popback** callout above. **Fix:** strip the `Cross-Origin-Opener-Policy` header from the auth/teams document responses (browser-automation interceptor or a debugging proxy) for the duration of **Authorize** — the opener survives, `notifySuccess` posts back, **Create** enables, and the connection goes **Draft → Ready**. Fallback: Microsoft support ticket with the repro in the callout. |
| Validation fails: *"not configured as a multi-tenant application"* | App registration is single-tenant | Set **Authentication → Supported account types → Accounts in any organizational directory (Multitenant)** (Part B). Server stays tenant-locked via issuer validation. |
| Empty / throttled PubMed results | NCBI rate limiting | Set `NCBI_API_KEY` (and `NCBI_EMAIL`) via `azd env set`, then `azd up`. |
| `/mcp` returns **421 Misdirected Request** | MCP DNS-rebinding protection rejects the public host, or HTTP/2 ingress | Keep `ALLOWED_HOSTS=*` (default) so the host check is disabled behind Azure ingress, and keep Container Apps ingress `transport: http`. Both are already configured in this repo. |
| After `azd provision`, `/mcp` returns 200 with no auth (hello-world page) | A standalone `azd provision` reset the container image to the Bicep placeholder | Run `azd deploy` to push the real image, or always use `azd up`. The Bicep also uses the azd "resource exists" pattern (`SERVICE_MCP_RESOURCE_EXISTS`) to preserve the deployed image on re-provision. |
| Changes not reflected | Propagation delay | Wait up to 15 minutes; re-test. |
| Need to inspect server logs | — | Azure portal → Container App → **Log stream**, or `az containerapp logs show -n ca-mcp-xxxx -g <resource-group> --follow`. |

---

## Clean up

```powershell
azd down --purge
```