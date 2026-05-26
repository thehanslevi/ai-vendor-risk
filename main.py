import json
import os
import sys
import textwrap

import anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    raise RuntimeError("ANTHROPIC_API_KEY is not set in .env")


RUBRIC = """\
Score each dimension on a 1–5 integer scale, where:
  1 = serious concern
  2 = below expectations
  3 = adequate
  4 = strong
  5 = best-in-class

Dimensions:

1. Data Handling & Privacy
   Data lineage documentation; whether the vendor trains on customer inputs;
   retention and deletion terms; PII handling and redaction controls.

2. Security Posture
   SOC 2 Type II; ISO 27001; breach history; access controls;
   AI-specific security such as prompt injection and data exfiltration via outputs.

3. Model Transparency & Explainability
   Model or system card availability; documented limitations and error modes;
   red-team or adversarial evaluation; disaggregated performance results.

4. Bias, Fairness & Harm
   Documented bias testing; decision logs; contestability of decisions;
   identification of affected populations.

5. Vendor Stability & Lock-in
   Company maturity; funding; data portability; exit terms.

6. Regulatory & Compliance Alignment
   EU AI Act posture; NIST AI RMF alignment; ISO 42001 status;
   sector-specific rules.

7. Agentic Autonomy & Oversight
   Degree of autonomous action the tool takes; human-in-the-loop controls;
   identity and authorization for agent actions; monitoring and logging of agent behavior.
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

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.AuthenticationError:
        print("ERROR: Anthropic authentication failed. Check ANTHROPIC_API_KEY in .env.", file=sys.stderr)
        sys.exit(1)
    except anthropic.APIConnectionError as e:
        print(f"ERROR: Could not reach the Anthropic API (network issue): {e}", file=sys.stderr)
        sys.exit(1)
    except anthropic.RateLimitError:
        print("ERROR: Anthropic rate limit exceeded. Wait a moment and try again.", file=sys.stderr)
        sys.exit(1)
    except anthropic.APIError as e:
        print(f"ERROR: Anthropic API error: {e}", file=sys.stderr)
        sys.exit(1)

    return response.content[0].text


def parse_response(raw: str) -> dict:
    text = raw.strip()

    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"ERROR: Could not parse JSON from model response: {e}", file=sys.stderr)
        print("--- raw response ---", file=sys.stderr)
        print(raw, file=sys.stderr)
        print("--- end raw response ---", file=sys.stderr)
        sys.exit(1)


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


if __name__ == "__main__":
    raw = score_vendor(VENDOR)
    result = parse_response(raw)
    print(format_report(result, VENDOR))
