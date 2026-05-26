import json
import os
import sys
import textwrap
from datetime import date

import anthropic
from dotenv import load_dotenv
from pyairtable import Api
from pyairtable.formulas import match

load_dotenv(override=True)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    raise RuntimeError("ANTHROPIC_API_KEY is not set in .env")

AIRTABLE_TOKEN = os.environ.get("AIRTABLE_TOKEN")
if not AIRTABLE_TOKEN:
    raise RuntimeError("AIRTABLE_TOKEN is not set in .env")

AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID")
if not AIRTABLE_BASE_ID:
    raise RuntimeError("AIRTABLE_BASE_ID is not set in .env")

AIRTABLE_TABLE_NAME = "Vendors"


RUBRIC = """\
You are assessing an AI vendor against a seven-dimension risk rubric. Score each dimension from 1 to 5 using the anchored descriptions below. Use the FULL range: 1 and 5 are reachable scores, not theoretical extremes. If your scores across the seven dimensions are all clustering at 3, treat that as a signal to look harder and differentiate. Different vendors should produce genuinely different scores.

EVIDENCE HANDLING: Score based on what the vendor context states. Where information is absent, do not assume the best or the worst. Absence of public documentation is itself a moderate risk signal (it limits assurance), but it is not equivalent to a confirmed failure. Distinguish "verified absent" from "not disclosed" in your reasoning.

DIMENSION 1 - Data Handling & Privacy
5: No training on customer data, contractually guaranteed; documented data lineage; granular retention/deletion controls; automated PII handling.
4: No training on customer data by default; clear retention terms; some PII controls.
3: Stated no-training posture but limited detail; basic retention controls; PII handling unclear.
2: Trains on customer data by default with opt-out, OR significant ambiguity in data practices.
1: Trains on customer data with no clear opt-out, OR documented misuse or misleading data claims.

DIMENSION 2 - Security Posture
5: SOC 2 Type II AND ISO 27001, current; documented AI-specific security (prompt injection, output exfiltration); independent red-team testing.
4: SOC 2 Type II and/or ISO 27001 current; strong access controls; some AI-specific security.
3: SOC 2 Type II only, or certifications stated but unconfirmed; standard controls; no AI-specific security documented.
2: Security claims without independent certification, OR certified but with documented security incidents.
1: No verifiable security certification AND documented breaches or critical unresolved vulnerabilities.

DIMENSION 3 - Model Transparency & Explainability
5: Public model/system card; documented limitations and error modes; published red-team/adversarial evaluation; disaggregated performance results.
4: Model/system card available; some documented limitations; partial evaluation disclosure.
3: Limited public model documentation; vendor describes capabilities but not limitations or evaluation.
2: No model card; no documented limitations or evaluation results.
1: No transparency whatsoever; vendor actively opaque about model behavior.

DIMENSION 4 - Bias, Fairness & Harm
5: Documented bias testing with disaggregated results; clear contestability mechanism; identified affected populations; harm-reporting pathway.
4: Some documented bias testing or fairness evaluation; a contestability or reporting pathway exists.
3: Bias acknowledged as a consideration but no documented testing or disaggregated results.
2: No bias documentation; the use case carries known fairness risks (e.g., demographic-sensitive outputs).
1: No bias consideration AND the tool enables a high-harm capability (e.g., synthetic likeness, autonomous decisions affecting people).

DIMENSION 5 - Vendor Stability & Lock-in
5: Mature, well-capitalized vendor; full data portability; clear exit terms; minimal lock-in.
4: Established vendor; reasonable portability; standard exit terms.
3: Viable vendor but some concentration risk; partial data portability.
2: Early-stage or thinly documented vendor; limited portability; meaningful lock-in.
1: Unstable vendor outlook OR no realistic data export / exit path. (For self-hosted/open deployments, score stability on the deploying organization's own capacity to maintain the system.)

DIMENSION 6 - Regulatory & Compliance Alignment
5: ISO 42001 certified; explicit EU AI Act and NIST AI RMF posture; sector-specific compliance (HIPAA, etc.) where relevant.
4: ISO 42001 certified OR strong stated alignment with EU AI Act / NIST AI RMF.
3: General compliance (GDPR/CCPA) but no AI-specific regulatory posture (no ISO 42001, no EU AI Act statement).
2: Minimal or generic compliance documentation; no AI-specific framework alignment.
1: No demonstrable regulatory posture; compliance gaps for the intended use.

DIMENSION 7 - Agentic Autonomy & Oversight
5: Tool is non-agentic OR fully autonomous with strong human-in-the-loop controls, scoped authorization, and complete action logging.
4: Some autonomous action with configurable oversight and logging available.
3: Moderate autonomy (acts without per-action approval) but bounded blast radius; basic oversight.
2: High autonomy taking downstream actions; oversight depends entirely on customer configuration; thin logging.
1: High autonomy with no built-in oversight, authorization scoping, or action logging.

SCORING OUTPUT:
Compute overall_score as the average of the seven dimension scores, to one decimal place.
Map to risk_tier: 4.0 and above = "Low Risk"; 2.5 to 3.9 = "Moderate Risk"; below 2.5 = "High Risk".
"""


VENDOR = {
    "vendor_name": "Otter.ai",
    "tool": "Otter Meeting Assistant",
    "description": "Joins and transcribes meetings, generates summaries automatically",
    "vendor_context": "Records and stores meeting audio; consumer and business tiers; data handling has drawn scrutiny",
}


def build_prompt(vendor: dict) -> str:
    return f"""\
You are an AI vendor-risk analyst. Assess the following vendor against the rubric below.

VENDOR
  Name: {vendor['vendor_name']}
  Tool: {vendor['tool']}
  Description: {vendor['description']}
  Context: {vendor['vendor_context']}

RUBRIC
{RUBRIC}

INSTRUCTIONS
Score each of the seven dimensions on the 1–5 scale defined above. Base your reasoning
on what is publicly known about the vendor and tool. If information is unknown, say so
in the reasoning and score conservatively.

Compute:
  - overall_score = arithmetic mean of the seven scores, rounded to ONE decimal place.
  - risk_tier:
      "Low Risk"      if overall_score >= 4.0
      "Moderate Risk" if 2.5 <= overall_score < 4.0
      "High Risk"     if overall_score < 2.5

OUTPUT FORMAT
Respond with ONE JSON object and NOTHING ELSE. No preamble. No explanation.
No markdown code fences. No trailing text. The JSON must match this exact shape:

{{
  "dimensions": [
    {{"name": "Data Handling & Privacy", "score": 3, "reasoning": "One to two sentences."}},
    {{"name": "Security Posture", "score": 3, "reasoning": "One to two sentences."}},
    {{"name": "Model Transparency & Explainability", "score": 3, "reasoning": "One to two sentences."}},
    {{"name": "Bias, Fairness & Harm", "score": 3, "reasoning": "One to two sentences."}},
    {{"name": "Vendor Stability & Lock-in", "score": 3, "reasoning": "One to two sentences."}},
    {{"name": "Regulatory & Compliance Alignment", "score": 3, "reasoning": "One to two sentences."}},
    {{"name": "Agentic Autonomy & Oversight", "score": 3, "reasoning": "One to two sentences."}}
  ],
  "overall_score": 3.0,
  "risk_tier": "Moderate Risk",
  "summary": "One to two sentence executive summary.",
  "recommended_action": "Short phrase, e.g. 'Approve with conditions' or 'Request SOC 2 report'."
}}
"""


MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 2000


def score_vendor(vendor: dict) -> str:
    prompt = build_prompt(vendor)
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def parse_response(raw: str) -> dict:
    text = raw.strip()

    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    text = text.strip()

    return json.loads(text)


def format_report(result: dict, vendor: dict) -> str:
    width = 80
    bar = "=" * width
    rule = "-" * width
    lines = []

    lines.append(bar)
    lines.append("VENDOR RISK ASSESSMENT")
    lines.append(bar)
    lines.append(f"Vendor: {vendor['vendor_name']}")
    lines.append(f"Tool:   {vendor['tool']}")
    lines.append("")
    lines.append("DIMENSIONS")
    lines.append(rule)

    for dim in result["dimensions"]:
        lines.append(f"[{dim['score']}/5] {dim['name']}")
        lines.append(textwrap.fill(
            dim["reasoning"],
            width=width,
            initial_indent="      ",
            subsequent_indent="      ",
        ))
        lines.append("")

    lines.append(bar)
    lines.append(f"Overall Score: {result['overall_score']} / 5")
    lines.append(f"Risk Tier:     {result['risk_tier']}")
    lines.append("")
    lines.append("Summary:")
    lines.append(textwrap.fill(
        result["summary"],
        width=width,
        initial_indent="  ",
        subsequent_indent="  ",
    ))
    lines.append("")
    lines.append("Recommended Action:")
    lines.append(textwrap.fill(
        result["recommended_action"],
        width=width,
        initial_indent="  ",
        subsequent_indent="  ",
    ))
    lines.append(bar)

    return "\n".join(lines)


def get_vendors_table():
    api = Api(AIRTABLE_TOKEN)
    return api.table(AIRTABLE_BASE_ID, AIRTABLE_TABLE_NAME)


def record_to_vendor(record: dict) -> dict:
    fields = record.get("fields", {})
    return {
        "vendor_name":    fields.get("Vendor Name", ""),
        "tool":           fields.get("Tool / Product", ""),
        "description":    fields.get("Description", ""),
        "vendor_context": fields.get("Vendor Context", ""),
    }


def format_dimension_scores(dimensions: list) -> str:
    blocks = []
    for dim in dimensions:
        blocks.append(f"[{dim['score']}/5] {dim['name']}\n  {dim['reasoning']}")
    return "\n\n".join(blocks)


def write_result_to_airtable(table, record_id: str, result: dict) -> None:
    fields = {
        "Status":              "Scored",
        "Overall Score":       result["overall_score"],
        "Risk Tier":           result["risk_tier"],
        "Recommended Action":  result["recommended_action"],
        "Assessment Summary":  result["summary"],
        "Dimension Scores":    format_dimension_scores(result["dimensions"]),
        "Last Scored":         date.today().isoformat(),
    }
    table.update(record_id, fields)


def mark_error(table, record_id: str) -> None:
    try:
        table.update(record_id, {"Status": "Error"})
    except Exception as e:
        print(f"     (could not mark row as Error in Airtable: {e})", file=sys.stderr)


if __name__ == "__main__":
    table = get_vendors_table()
    pending = table.all(formula=match({"Status": "Needs Review"}))
    print(f"Found {len(pending)} record(s) with Status = 'Needs Review'.")

    if not pending:
        sys.exit(0)

    successes = 0
    failures = 0

    for i, record in enumerate(pending, start=1):
        vendor = record_to_vendor(record)
        label = f"{vendor['vendor_name']} / {vendor['tool']}"
        print(f"[{i}/{len(pending)}] {label} ... ", end="", flush=True)

        try:
            raw = score_vendor(vendor)
            result = parse_response(raw)
            write_result_to_airtable(table, record["id"], result)
            print(f"[ok] {result['overall_score']} -> {result['risk_tier']}")
            successes += 1
        except anthropic.AuthenticationError:
            print("[fail] authentication error -- aborting loop")
            print("Check ANTHROPIC_API_KEY in .env. Remaining records left untouched.", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"[fail] {type(e).__name__}: {e}")
            mark_error(table, record["id"])
            failures += 1

    print(f"\nDone. {successes} scored, {failures} marked Error.")
