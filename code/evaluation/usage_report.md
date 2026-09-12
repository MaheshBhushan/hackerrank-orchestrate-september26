# Token usage and cost — final 250-request run

## Scope

These figures describe the terminal run of `python3 code/main.py` that produced the delivered `output.csv`. The exact output SHA-256 and run timestamp are recorded in `run_report.json`.

| Provider/model in prediction run | Calls | Input tokens | Output tokens | Total tokens | Estimated API cost |
| --- | ---: | ---: | ---: | ---: | ---: |
| None — local Python with cached evidence | 0 | 0 | 0 | 0 | USD 0 |
| Overall | 0 | 0 | 0 | 0 | USD 0 |

- Requests: 250.
- Average model calls per request: 0.
- Average input/output/total tokens per request: 0 / 0 / 0.
- Estimated total prediction API cost: USD 0.
- Estimated prediction API cost per request: USD 0.

## Evidence preprocessing and development disclosure

OpenAI Codex was used to build and review the solver and visually interpret all 16 supplied images. Local Tesseract OCR assisted extraction. The verified image facts are cached by SHA-256 in `image_facts.json` and checked against the actual PNGs every run. English/Indonesian messages are parsed locally by a limited financial-fact grammar. Explanations are generated from computed values using templates.

The zero-cost table does **not** claim that development or initial AI-assisted image interpretation consumed no tokens or incurred no subscription/model cost. The exact backing model identifier, metered development input/output tokens, and attributable development cost were not exposed to the solution process and are not fabricated here. Codex development usage is outside the stated final-run scope. Tesseract uses local compute, not a token-billed model API. No new OCR or model call is made by the final cached prediction run.

If an input image changes, the solver stops rather than reusing an invalid cached extraction. A fresh extraction would require an updated evidence cache and a new usage report for any model calls used in that run.
