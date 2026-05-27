# AI Vendor Risk Assessment

Built by Hannah Levinson. More at hrlevinson.com

A Python tool that scores AI vendors against a seven-dimension governance rubric using the Anthropic API, with Airtable as the system of record.

## Overview

The tool reads AI vendor records from an Airtable table, scores each against a seven-dimension governance rubric using Claude (a current Anthropic model), and writes structured risk assessments — per-dimension scores, an overall score, a risk tier, a summary, and a recommended action — back to the row. A run over ten vendors takes about two to three minutes.

It addresses a common gap in AI adoption. Organizations now evaluate AI vendors across a wider set of risk surfaces than traditional procurement covers — data handling, model transparency, fairness, agentic behavior, regulatory posture — but most teams do this ad hoc, with inconsistent depth between reviewers and across vendors. This tool produces consistent, defensible first-pass assessments that a human reviewer can ratify or override.

## How it works

The pipeline:

1. Load credentials from a local `.env` file (Anthropic API key, Airtable token, base ID).
2. Connect to the Airtable `Vendors` table.
3. Query for records with `Status = "Needs Review"`.
4. For each record, map its Airtable fields into a vendor dictionary.
5. Build a prompt that combines the vendor details with the rubric and requests a strict JSON response: seven dimension scores, an overall score, a risk tier, a one-to-two-sentence summary, and a recommended action.
6. Call the Anthropic API.
7. Parse the response defensively, stripping any stray markdown fences before `json.loads`.
8. Write the parsed result back to the row and set its status to `Scored`.

Each vendor is wrapped in its own `try`/`except`. A failure on one row — a malformed response, a transient network error — marks that row's status as `Error`, logs the cause, and continues to the next vendor rather than aborting the run. Authentication errors are the one exception: a bad API key fails for every vendor, so the loop exits early rather than continuing.

## The rubric

Each vendor is scored against seven dimensions:

1. **Data Handling & Privacy** — training on customer data, data lineage, retention and deletion controls, PII handling.
2. **Security Posture** — SOC 2 Type II, ISO 27001, breach history, AI-specific controls such as prompt injection and output exfiltration.
3. **Model Transparency & Explainability** — model or system card availability, documented limitations, red-team evaluation, disaggregated performance results.
4. **Bias, Fairness & Harm** — bias testing, contestability, affected-population analysis, harm-reporting pathways.
5. **Vendor Stability & Lock-in** — company maturity, data portability, exit terms.
6. **Regulatory & Compliance Alignment** — EU AI Act posture, NIST AI RMF alignment, ISO 42001, sector-specific rules.
7. **Agentic Autonomy & Oversight** — degree of autonomous action, human-in-the-loop controls, action logging.

Each dimension is scored from 1 to 5 against anchored level descriptions specific to that dimension. The overall score is the mean of the seven, rounded to one decimal place. Risk tier follows from the overall score: 4.0 and above is Low Risk, 2.5 to 3.9 is Moderate Risk, below 2.5 is High Risk.

The rubric reflects AI governance standards current as of May 2026 — the EU AI Act, the NIST AI Risk Management Framework, and ISO/IEC 42001. The full rubric text, including the anchor descriptions for each level, lives in the `RUBRIC` constant at the top of `main.py`.

## Engineering notes

Secrets (Anthropic API key, Airtable token, base ID) live in a git-ignored `.env` file loaded with `python-dotenv`; the script fails fast with a clear message if any are missing. The model is prompted to return a single JSON object matching an explicit schema, and the parser strips any markdown fences before `json.loads`, since the model occasionally wraps output in fences despite the prompt forbidding it. Each vendor is processed inside its own `try`/`except` so a single bad row marks that row's `Status` as `Error` and the loop continues, rather than halting the whole run. The current rubric is the result of one recalibration pass. The first ten-vendor run produced center-clustered scores. On inspection, two compounding causes emerged: uneven `Vendor Context` inputs (some rows had thin, generic descriptions while others had specifics), and rubric anchors that defined the extremes only as "serious concern" and "best-in-class" without concrete level descriptions between them. Both were addressed: the rubric got anchored 1–5 level descriptions per dimension, and the `Vendor Context` field for each row was rewritten by hand to consistent depth before the re-run. The re-run widened the distribution; scores spanned 2.1 to 4.3, and two vendors cleared the Low Risk threshold for the first time.

## Sample results

Snapshot of the recalibrated ten-vendor run on 2026-05-26, sorted by overall score (descending).

| Vendor | Tool | Overall Score | Risk Tier |
|---|---|---:|---|
| OpenAI | ChatGPT Enterprise | 4.3 | Low Risk |
| Google | Gemini for Workspace | 4.1 | Low Risk |
| Microsoft | Copilot Studio | 3.9 | Moderate Risk |
| Glean | Glean Assistant | 3.9 | Moderate Risk |
| Harvey | Harvey AI | 3.4 | Moderate Risk |
| Perplexity | Perplexity Enterprise Pro | 2.9 | Moderate Risk |
| Hugging Face | Open-source model (self-hosted) | 2.9 | Moderate Risk |
| Otter.ai | Otter Meeting Assistant | 2.4 | High Risk |
| HeyGen | HeyGen Avatars | 2.3 | High Risk |
| Lovable | Lovable | 2.1 | High Risk |

Tier distribution: 2 Low Risk, 5 Moderate Risk, 3 High Risk.

## Setup

### Prerequisites

- Python 3.9 or newer.
- An Anthropic API key with access to the Claude API (see https://console.anthropic.com).
- An Airtable personal access token with `data.records:read` and `data.records:write` scopes on the target base (see https://airtable.com/create/tokens).
- An Airtable base containing a `Vendors` table matching the schema below.

### Install

```bash
git clone <repository-url>
cd ai-vendor-risk
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Configure

Create a `.env` file in the project root:

```
ANTHROPIC_API_KEY=
AIRTABLE_TOKEN=
AIRTABLE_BASE_ID=
```

Fill each value with no quotes and no spaces around `=`. The `.env` file is git-ignored and should never be committed.

### Airtable schema

The script expects a single table named `Vendors` with these fields:

| Field | Type | Direction |
|---|---|---|
| Vendor Name | Text | Input |
| Tool / Product | Text | Input |
| Description | Long text | Input |
| Vendor Context | Long text | Input |
| Status | Single select (`Needs Review`, `Scored`, `Error`) | Input and output |
| Overall Score | Number, 1 decimal | Output |
| Risk Tier | Single select (`Low Risk`, `Moderate Risk`, `High Risk`) | Output |
| Recommended Action | Text | Output |
| Assessment Summary | Long text | Output |
| Dimension Scores | Long text | Output |
| Last Scored | Date | Output |

The script reads the four input fields, populates the six output fields, and updates `Status` from `Needs Review` to `Scored` (or `Error` on failure).

## Running it

With the virtualenv activated and `.env` populated:

```bash
python main.py
```

The script queries the `Vendors` table for all records with `Status = "Needs Review"`, scores each in turn, and writes results back to the row. It prints a one-line progress entry per vendor (for example `[3/10] HeyGen / HeyGen Avatars ... [ok] 2.3 -> High Risk`) followed by a final success/error count. A ten-vendor run typically takes two to three minutes; API cost is on the order of a few cents per vendor at current Anthropic rates. Rows that score successfully end with `Status = Scored`; rows that fail end with `Status = Error` and the failure reason is printed to the terminal.

## Limitations and next steps

### Limitations

The tool scores whatever vendor context a human enters in Airtable. It does not enrich, research, or fact-check input. If the `Vendor Context` field is thin or out of date, the score reflects that. Keeping the input fields current is a human responsibility, and vendor postures change over time (certifications expire, breaches occur, model documentation updates), so inputs should be refreshed periodically.

The output is a first-pass risk assessment, not a procurement decision. It is intended to give a human reviewer a structured, consistent starting point: the rubric is applied the same way for every vendor, which a human reviewer alone cannot guarantee. A human is still required to ratify, override, or supplement the result. A 4.3 from this tool does not authorize a deployment; a 2.1 does not require a ban.

The rubric reflects governance standards current as of May 2026. Standards drift. Periodic review of the `RUBRIC` constant against the prevailing regulatory landscape (EU AI Act technical guidance updates, NIST AI RMF revisions, new sector rules) is part of keeping the tool useful.

### Possible extensions

- **Configurable rubric weights.** The current overall score is an unweighted mean across the seven dimensions. For some use cases (regulated-industry deployments, for example), Data Handling & Privacy or Regulatory Alignment should weigh heavier than Vendor Stability.
- **Observability and logging.** Run history is not currently persisted outside Airtable. A structured log of each run (vendor, score, model version, prompt hash, timestamp) would support trend analysis and audit.
- **Scheduled runs.** The tool is invoked manually today. A scheduled job (cron, GitHub Actions) could re-score vendors marked `Scored` on a regular cadence to catch drift in vendor postures.
- **Multi-table support.** The script is hardcoded to a single `Vendors` table; it could be made configurable for organizations tracking multiple categories of AI tooling separately.
