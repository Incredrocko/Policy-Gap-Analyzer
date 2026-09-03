# Local LLM Policy Gap Analysis & Improvement Module

A fully offline, local-LLM-powered tool that
compares an organizational policy against the CIS MS-ISAC / NIST
Cybersecurity Framework Policy Template Guide, reports gaps, revises the
policy to close them, and produces a NIST-CSF-aligned improvement roadmap.

---

## A. How to run it

### One-time setup

```bash
# 1. Ollama itself (not a pip package) -- see https://ollama.com
curl -fsSL https://ollama.com/install.sh | sh   # Linux; use the installer on Mac/Windows

# 2. Pull a small local chat model
ollama pull llama3.2:3b        # or qwen2.5:3b / phi3:mini -- any small instruction-tuned model

# 3. Python deps
pip install -r requirements.txt --break-system-packages

# 4. Parse the reference PDF into structured data (already done -- data/nist_csf_mapping.json
#    is checked in -- but here's how to regenerate it, e.g. against a newer guide)
python build_reference_data.py
```

### Single policy

```bash
python main.py \
  --policy data/dummy_policies/patch_management_policy.txt \
  --domain "Patch Management" \
  --outdir output/
```

`--domain` must be one of:
`Information Security Management System (ISMS)`, `Data Privacy and Security`,
`Patch Management`, `Risk Management`.

Outputs land in `output/`:
- `gap_report.md` -- every NIST CSF requirement checked for the domain,
  grouped by function, marked covered / partial / not-covered
- `revised_policy.md` -- the policy rewritten to close the gaps
- `roadmap.md` -- prioritized improvement roadmap by NIST CSF function

### Full evaluation (all four dummy policies, with scoring)

```bash
python evaluate.py                                  # all 4 domains + LLM-as-judge scoring
python evaluate.py --skip-judge                      # faster, no judge pass
python evaluate.py --domain "Risk Management"        # just one domain
```

Writes `output/evaluation/<domain>/{gap_report,revised_policy,roadmap,judge_verdicts}.md`
plus `output/evaluation/evaluation_summary.md` with a coverage table across
all domains (requirements checked, gaps found, coverage before/after revision,
judge score).

### Automated tests (no live Ollama required)

```bash
python -m unittest discover -s tests -v
```

12 tests covering the reference-data resolution, the batching/retry logic in
gap analysis, the revision/roadmap/judge calls, and a regression test for a
key-collision bug caught during development (see Section D). These run
against a stubbed LLM client, so they verify the pipeline's *logic* is
correct independent of any particular model's output quality -- run them any
time you change the prompts or the merge/parsing code.

---

## B. Dependencies

- **Ollama** (external, not pip) -- runs the local model, serves an HTTP API
  on `localhost:11434`. This is what satisfies "no external API / cloud
  service": the only network calls in the whole pipeline are to localhost.
- **Python 3.10+** (uses `list[dict]` style type hints and `X | None` unions)
- `requests` -- HTTP calls to Ollama
- `pypdf` -- text extraction from the reference PDF and PDF policy inputs
- `python-docx` -- support for `.docx` policy inputs

No embedding model, no vector database, no GPU requirement beyond whatever
the chosen Ollama model needs (a 3B model runs fine on CPU, just slower).

---

## C. Logic and workflow

### Why this architecture

The CIS/MS-ISAC guide is **not prose to search semantically** -- it's a
structured table: 99 NIST CSF subcategories (e.g. `GV.OC-01`), each with a
one-sentence requirement and a bullet list of policy/standard template names
it applies to. That's a lookup table, not a corpus, so a RAG pipeline
(chunk + embed + retrieve) would be solving a problem this document doesn't
have. Instead:

1. **`build_reference_data.py`** parses the PDF once into structured JSON
   (`data/nist_csf_mapping.json`) using regex over the guide's very regular
   layout -- no LLM or embeddings involved.
2. **`config.DOMAIN_POLICY_MAP`** maps each of the four problem-statement
   domains to the guide's own template names (e.g. "Patch Management" →
   `Patch Management Standard`, `Maintenance Policy`, `Configuration
   Management Policy`, `Secure Configuration Standard`, `Vulnerability
   Scanning Standard`). This mapping is a judgment call -- the four domains
   don't appear verbatim in the guide -- and is the one place you should
   sanity-check against your own policies if results look off.
3. **`reference_data.get_domain_requirements(domain)`** intersects the
   domain's template names against every subcategory's `policies` list --
   a deterministic set operation, not a retrieval step. Coverage per domain:
   ISMS 44 requirements, Data Privacy and Security 29, Patch Management 27,
   Risk Management 28 (some requirements are shared across domains, since a
   subcategory can map to multiple template names).
4. **`gap_analysis._call_batch`** sends the *whole* policy text plus a batch
   of ~10 requirements to the LLM (`format: "json"`), asking for a
   covered/partial/not_covered verdict on each. If the response is malformed
   or missing verdicts for some ids, it retries (up to
   `config.MAX_LLM_RETRIES`) with a corrective note listing exactly which
   ids are missing. If verdicts are still missing after retries, those
   requirements get a clearly-flagged `_verdict_missing` placeholder
   (counted as a gap, but visibly marked "unverified" in the report) rather
   than silently vanishing.
5. **`policy_revision.revise_policy`** sends the original policy + the full
   gap list to the LLM and asks for a rewritten policy addressing every gap.
6. **`policy_revision.generate_roadmap`** turns the same gap list into a
   prioritized action table.
7. **`policy_revision.judge_revision`** (evaluation only) makes an
   *independent* LLM call -- given only the gap list and the revised policy,
   not the revision step's own reasoning -- to check whether each gap was
   actually closed. This exists because trusting the revision step to grade
   its own homework would be circular; the judge pass is a second,
   differently-framed check.
8. **`main.py`** runs steps 4-6 for one policy. **`evaluate.py`** runs
   steps 4-7 for all four dummy policies and aggregates a summary table.

### File map

| File | Role |
|---|---|
| `build_reference_data.py` | PDF → structured JSON (one-time) |
| `reference_data.py` | domain → requirement list lookup |
| `pdf_utils.py` | text extraction (PDF/.docx/.txt) |
| `ollama_client.py` | HTTP wrapper around local Ollama, with connection-error handling |
| `prompts.py` | all prompt templates (gap check, revision, roadmap, judge) |
| `gap_analysis.py` | Task 1: batched requirement checking with retry logic |
| `policy_revision.py` | Task 2: revision, roadmap, judge |
| `main.py` | CLI for a single policy |
| `evaluate.py` | evaluation harness across all four dummy policies |
| `tests/test_pipeline.py` | unit tests against a stubbed LLM |
| `data/dummy_policies/*.txt` | the four test policies (deliberately incomplete, for demo purposes) |
| `data/nist_csf_mapping.json` | parsed reference data |

---

## D. Limitations and future improvements

- **`config.DOMAIN_POLICY_MAP` is a judgment call**, not derived from the
  source document -- the four domains in the problem statement don't appear
  verbatim in the guide's own template names. It's been sanity-checked
  against the dummy policies (every domain resolves to a non-empty,
  plausible requirement set), but a domain expert might redistribute a
  template or two.
- **Whole-policy-in-one-prompt.** For policies the length of the dummy
  policies here, sending the full text with every batch is fine. A much
  longer real-world policy would need chunking to fit model context --
  `pdf_utils.split_policy_into_sections` exists for this but isn't wired
  into the default pipeline yet.
- **Two data-quality quirks in the source PDF itself** (not this code's
  bug, but worth knowing): `GV.OC-04` and `GV.OC-05` have identical
  description text (looks like a copy-paste error in CIS's original
  document), and one entry (`RS.CO-3`) uses inconsistent zero-padding in
  its ID and gets silently absorbed into the preceding entry by the current
  parser's regex (which requires exactly 2 digits). Neither breaks the
  pipeline, but a stricter parser could recover that one entry.
- **JSON-parsing robustness has a ceiling.** The retry loop
  (`gap_analysis._call_batch`) recovers from a model that returns malformed
  JSON or drops some ids, but if a 3B model's JSON is *consistently* broken
  for a given prompt, retries won't fix that -- the eventual fallback is a
  flagged "unverified" placeholder, which is safe (never silently drops a
  requirement) but not a substitute for a model that follows the schema.
  Larger/better-instruction-following local models will need this less.
- **The judge pass grades text presence, not real-world adequacy.** It
  checks whether the revised policy *contains language addressing* a gap,
  not whether that language would actually satisfy an auditor or hold up
  in practice. Useful as a regression check across pipeline changes, not a
  substitute for human policy review.
- **A regression test caught one real bug worth flagging explicitly:**
  during development, merging the LLM's gap verdict onto the original
  requirement record used Python dict-unpacking (`{**req, **result}`), and
  both dicts happened to have a `"description"` key -- the requirement's
  NIST wording and the LLM's gap explanation. The unpacking silently
  dropped the original NIST text. Fixed by renaming the requirement's copy
  to `"requirement"` before merging; `tests/test_pipeline.py::
  test_requirement_text_survives_merge` guards against a regression. This
  is the kind of thing that's easy to miss if you're only eyeballing
  output rather than writing the test.
- **Single-file, single-language policies only.** No multi-document policy
  sets, no non-English input handling, no OCR for scanned/image-based PDF
  policies.
- **This environment couldn't run a live Ollama instance** (no network
  access in the sandbox this was built in), so the evaluation numbers
  you'll get from a real model will differ from anything shown during
  development -- everything above was verified for logical correctness
  against a stubbed client, not for real model output quality. Running
  `python evaluate.py` locally against your actual Ollama model is the
  real validation step.
