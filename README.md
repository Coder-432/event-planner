# Gather: Event Planner

Plan a birthday, community event, fundraiser or workshop by filling in one sentence.
Gather returns a budget, a dated timeline, a vendor checklist, personalized ideas and a
ready-to-send invitation. An AI model personalizes the ideas when one is available, and the
planner still works fully without one.

![Gather showing a plan for a birthday party](docs/preview.png)

## Features

- **Fill-in-the-blank form.** "I'm planning a *birthday* called *…* on *…*, for *25* people with *800* *USD* to spend."
- **Event types.** Birthday, community event, fundraiser, workshop, or **other** (you say what it is).
- **Any currency.** A dropdown with 155 active world currencies, formatted for your locale.
- **Budget.** A split by category that always adds up exactly to your total, shown as a proportional bar.
- **Timeline.** Dated steps counted back from your event date. If the date is close, lead times are compressed and the page says so.
- **Vendor checklist.** What to ask each vendor, with checkboxes and a progress bar.
- **Personalized ideas.** A theme, five ideas with costs, tips and an invitation, written around your interests and constraints (allergies, access needs, and so on).
- **Clear data.** Resets the form and the plan, and cancels a plan that is still being made.
- **Works anywhere.** Dark mode, phone-friendly, and no build step.

## How it works

| Part | What it does |
|---|---|
| Planner logic (`app.py` and the same logic in `index.html`) | Budget split, timeline and vendor questions are computed in code, so the numbers are always correct. |
| AI layer (`app.py`) | Sends your details to any OpenAI-compatible model and asks for a theme, ideas, tips and an invitation as JSON. |
| Fallback | If no model is reachable, template ideas are used. If the server is unreachable too (or you open `index.html` straight from disk), the page builds the plan itself and labels it "Built in your browser". |

"Make my plan" therefore always produces a plan. Only the AI personalization needs the server and a model.

## Quick start

Requires Python 3.10 or newer.

```bash
git clone https://github.com/<your-username>/gather-event-planner.git
cd gather-event-planner

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

uvicorn app:app --reload
```

Open <http://127.0.0.1:8000>.

### Add an AI model (optional)

The default is a local [Ollama](https://ollama.com) model:

```bash
ollama pull qwen2.5:7b-instruct
```

Leave Ollama running and restart the app. The badge above your plan changes to
"Personalized by AI".

To use another provider, set these environment variables before starting `uvicorn`:

| Variable | Default | Purpose |
|---|---|---|
| `LLM_BASE_URL` | `http://localhost:11434/v1` | Any OpenAI-compatible endpoint (Ollama, OpenAI, vLLM, LM Studio, and others) |
| `LLM_MODEL` | `qwen2.5:7b-instruct` | Model name |
| `LLM_API_KEY` | `ollama` | API key, if your provider needs one |
| `LLM_TIMEOUT` | `45` | Seconds to wait for the model before using template ideas |

Example with OpenAI:

```bash
export LLM_BASE_URL=https://api.openai.com/v1
export LLM_MODEL=gpt-4o-mini
export LLM_API_KEY=sk-...
uvicorn app:app --reload
```

Never commit an API key. Keep it in an environment variable.

## API

`POST /api/plan` accepts JSON:

| Field | Type | Notes |
|---|---|---|
| `event_type` | string | `birthday`, `community`, `fundraiser`, `workshop` or `other` |
| `other_type` | string | What kind of event, used when `event_type` is `other` |
| `currency` | string | ISO 4217 code such as `USD`, `INR`, `EUR` (default `USD`) |
| `name` | string | Event or guest of honor |
| `date` | string | `YYYY-MM-DD` (optional) |
| `guests` | integer | 1 to 5000 |
| `budget` | number | Greater than 0 |
| `location`, `interests`, `notes` | string | Free text used to personalize ideas |
| `honoree_age` | integer | Optional |
| `indoor_outdoor` | string | `indoor`, `outdoor` or `either` |

```bash
curl -X POST http://127.0.0.1:8000/api/plan \
  -H "Content-Type: application/json" \
  -d '{"event_type":"birthday","guests":25,"budget":800,"currency":"USD","interests":"dinosaurs, crafts"}'
```

The response contains `mode` (`ai` or `offline`), `personalized`, `budget`, `timeline` and `vendors`.
`GET /api/health` reports whether the model is reachable.

## Project structure

```
gather-event-planner/
├── app.py            FastAPI server, planner logic and AI call
├── index.html        The whole interface, with a built-in planner for offline use
├── requirements.txt
└── docs/preview.png
```

## Notes for contributors

- The planner data (budget shares, timelines, vendor questions, template ideas) lives in `app.py`
  and is duplicated in `index.html` so the page works without a server. If you change one,
  change the other.
- Preview panes and some embedded viewers block form submission, so the button uses a click
  handler instead of a form submit.

## Ideas for next steps

- Save and reopen plans (SQLite)
- Track actual spend against each budget line
- Export the timeline to a calendar file (.ics)
- A chat box for changes, such as "swap the entertainment and keep it under 100"

## License

Add a license before publishing if you want others to reuse the code (MIT is a common choice).
