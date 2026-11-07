# Weekly scan: instructions for the scheduled cloud run

You are a scheduled Claude Code cloud run on `neelnanda-io/nocot-bench`. Your job: find new
OpenRouter models worth placing on NCRI 15.2 / NCKI, rate them, refresh the NCRI Candidates page,
and email Neel. You spend no OpenRouter money beyond catalogue reads. Settings live in
`automation/config.json`.

1. **Scan.** `python -m automation.scan_openrouter`. It writes `automation/candidates.json` and
   updates `automation/seen.json`. If `OPENROUTER_API_KEY` is missing or openrouter.ai is blocked,
   stop and email Neel that the cloud environment needs Full network access and the key.
2. **Rate the new candidates.** The scan carries earlier unmeasured candidates forward with their
   ratings (`"new": false`); leave those alone. For each `"new": true` entry, edit
   `automation/candidates.json`: set `priority` to `high`,
   `medium` or `low` and `why` to one factual sentence. Base it only on the entry's name, lab,
   description, price, tool support and endpoints, plus `models.csv` (which of the lab's models are
   already on the ladder). Never invent benchmark results or claims.
   - **high**: a new release from a frontier or leading open-weight lab, or a new checkpoint of a
     family already on the ladder, with tool calling and a usable pin.
   - **medium**: plausible general model with a catch (unvetted
     host, no usable pin, unknown lab with a serious-looking release).
   - **low**: single-purpose, vision or image models, routers, tiny models, fine-tunes of something
     already listed, `-pro` variants that force long reasoning.
3. **Open requests.** List open measuring requests with the REST API (GraphQL is blocked here):
   `gh api 'repos/neelnanda-io/nocot-bench/issues?labels=measure&state=open'`. Write
   `automation/open_requests.json` as a list of `{number, url (html_url), models, created}`,
   where `models` are the `- <id>` lines under `models:` in each body.
4. **Render and publish.** `python -m automation.render_page`. Then read the artifact at
   `artifact_url` with the Artifact tool (action read), and publish `automation/page.html` to that
   same `url`. Declare no capabilities. If the publish asks for approval or fails, carry on and
   say so in the email.
5. **Commit to main.** `git add automation/candidates.json automation/seen.json` (nothing else),
   commit `scan: <date>, <n> candidates`, `git pull --rebase origin main`, push to `main`.
6. **Email Neel** with `python -m automation.send_email --subject "..." --body-file email.txt`
   (Resend, from `SENDER_EMAIL` to the address in the env var named by `notify_email_env`):
   subject `NCRI candidates: <n> new, <k> high priority`; body lists the high-priority models
   with their one-line reason and estimated buy cost, the OpenRouter balance (flag it if under
   $100), open requests, and the page link. Plain text, under 300 words.

