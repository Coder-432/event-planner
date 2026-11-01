"""Event Planner AI: birthdays and community events.

Budgets, timelines and vendor checklists are computed deterministically so the
numbers always add up. A language model (any OpenAI-compatible endpoint, e.g.
a local Ollama/Qwen) personalizes the ideas, theme and invitation text. If no
model is reachable, a built-in fallback keeps the app fully usable.

Run:  uvicorn app:app --reload
Env:  LLM_BASE_URL (default http://localhost:11434/v1)
      LLM_MODEL    (default qwen2.5:7b-instruct)
      LLM_API_KEY  (default "ollama")
      LLM_TIMEOUT  (default 45 seconds; after that the built-in templates are used)
"""
import datetime as dt
import json
import os
import re
from pathlib import Path
from typing import Literal, Optional

import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:7b-instruct")
LLM_API_KEY = os.getenv("LLM_API_KEY", "ollama")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "45"))  # seconds to wait for the model before using templates

app =FastAPI(title="Event Planner AI")
HERE = Path(__file__).parent

EventType = Literal["birthday", "community", "fundraiser", "workshop", "other"]


class PlanRequest(BaseModel):
    event_type: EventType = "birthday"
    other_type: str = Field("", max_length=80, description="What kind of event, when event_type is 'other'")
    currency: str = Field("USD", pattern=r"^[A-Za-z]{3}$", description="ISO 4217 code, e.g. USD, INR, EUR")
    name: str = Field("", max_length=120, description="Event or honoree name")
    date: Optional[dt.date] = None
    guests: int = Field(20, ge=1, le=5000)
    budget: float = Field(500, gt=0, le=10_000_000)
    location: str = Field("", max_length=120)
    honoree_age: Optional[int] = Field(None, ge=0, le=120)
    interests: str = Field("", max_length=500, description="Theme, hobbies, vibe")
    notes: str = Field("", max_length=800, description="Constraints, dietary, access")
    indoor_outdoor: Literal["indoor", "outdoor", "either"] = "either"


# ---- Deterministic planning knowledge --------------------------------------

# category -> share of budget (each template sums to 1.0)
BUDGET = {
    "birthday": {"Venue": .20, "Food & drink": .35, "Cake & desserts": .08,
                 "Decor & balloons": .10, "Entertainment / activities": .12,
                 "Invitations & favors": .05, "Contingency": .10},
    "community": {"Venue & permits": .15, "Food & drink": .25, "Entertainment & speakers": .15,
                  "Equipment & AV": .12, "Marketing & printing": .10, "Insurance & safety": .08,
                  "Supplies & signage": .07, "Contingency": .08},
    "fundraiser": {"Venue": .18, "Food & drink": .28, "Auction / raffle items": .10,
                   "Entertainment": .12, "Marketing & printing": .10, "Payment & admin fees": .05,
                   "Decor & signage": .07, "Contingency": .10},
    "workshop": {"Venue": .25, "Facilitator / speaker": .25, "Materials & supplies": .15,
                 "Refreshments": .15, "Marketing": .08, "AV & tech": .05, "Contingency": .07},
    "other": {"Venue": .22, "Food & drink": .30, "Entertainment & activities": .13, "Decor & supplies": .10,
              "Marketing & invitations": .08, "Equipment & AV": .07, "Contingency": .10},
}

# (days before event, task)
TIMELINE = {
    "birthday": [(42, "Set budget, date and guest list"), (35, "Pick theme and book venue"),
                 (28, "Book key vendors (caterer, entertainer, photographer)"),
                 (21, "Send invitations"), (14, "Order cake and decor; plan menu and activities"),
                 (7, "Confirm RSVPs and dietary needs; buy supplies and favors"),
                 (3, "Confirm vendors and delivery times; prep playlist and schedule"),
                 (1, "Set up venue, pick up cake and ice"), (0, "Event day: run schedule, take photos"),
                 (-2, "Send thank-yous and settle final vendor payments")],
    "community": [(84, "Define goals, committee roles and budget"), (70, "Secure venue, date and permits"),
                  (56, "Recruit sponsors, vendors and volunteers"), (42, "Confirm insurance and safety plan"),
                  (35, "Launch promotion: social, flyers, local partners"),
                  (21, "Finalize program, schedule and vendor layout"),
                  (14, "Brief volunteers; confirm equipment and AV"), (7, "Final headcount, signage, weather plan"),
                  (1, "Load-in and setup walkthrough"), (0, "Event day: check-in, run program, collect feedback"),
                  (-3, "Thank sponsors/volunteers; publish recap and reconcile budget")],
    "fundraiser": [(90, "Set fundraising goal, committee and budget"), (75, "Book venue and secure licenses"),
                   (60, "Solicit auction/raffle donations and sponsors"), (42, "Open ticket sales and donation page"),
                   (28, "Promote with email, social and press"), (14, "Finalize program, MC and donor recognition"),
                   (7, "Confirm attendance and volunteers; print bid sheets"), (1, "Setup and payment test"),
                   (0, "Event day: run program and make the ask"), (-3, "Send receipts, thank donors, report results")],
    "workshop": [(56, "Define learning goals and audience"), (42, "Book facilitator and venue"),
                 (35, "Open registration and promote"), (21, "Finalize agenda and materials list"),
                 (10, "Order or print materials"), (5, "Confirm attendees; send logistics email"),
                 (1, "Room setup and tech check"), (0, "Workshop day"), (-2, "Send follow-up resources and survey")],
    "other": [(56, "Define the purpose, guest list and budget"), (42, "Pick the date and book the venue"),
              (28, "Book key vendors and any speakers or performers"), (21, "Send invitations or open registration"),
              (14, "Finalize menu, program and supplies"), (7, "Confirm headcount and special requirements"),
              (2, "Confirm vendor arrival times and run through the schedule"), (1, "Set up and do a walkthrough"),
              (0, "Event day"), (-2, "Thank guests and helpers; settle payments")],
}

# budget category -> vendor checklist (what to ask / confirm)
VENDORS = {
    "Venue": ["Total cost incl. fees and deposit", "Capacity, rain plan and accessibility", "Setup/cleanup time and rules"],
    "Venue & permits": ["Permit and noise/alcohol rules", "Capacity and accessibility", "Deposit and cancellation terms"],
    "Food & drink": ["Per-head price and minimums", "Dietary options (veg, vegan, allergens)", "Serving staff, plates, cleanup"],
    "Cake & desserts": ["Flavors, allergen info, serving count", "Pickup/delivery time", "Order lead time"],
    "Decor & balloons": ["Theme palette and delivery vs DIY", "Setup/teardown help", "Venue rules on tape or helium"],
    "Entertainment / activities": ["Age-appropriate content and duration", "Equipment and space needs", "Backup if they cancel"],
    "Entertainment & speakers": ["Fee, travel and tech riders", "Run time and soundcheck slot", "Signed agreement"],
    "Entertainment": ["Fee and set length", "Power and stage needs", "Signed agreement"],
    "Invitations & favors": ["Digital vs printed, RSVP tracking", "Favor count (+10%)", "Delivery date"],
    "Equipment & AV": ["Mics, speakers, projector, power", "Tables, chairs, tents count", "Tech on site during event"],
    "AV & tech": ["Projector/screen/mic check", "Wi-Fi and power access", "Tech contact on the day"],
    "Marketing & printing": ["Flyer/poster proofs", "Social and local listings", "Print turnaround"],
    "Marketing": ["Registration page and reminders", "Flyer/social assets", "Partner cross-promotion"],
    "Insurance & safety": ["Event liability coverage", "First aid and safety lead", "Crowd and emergency plan"],
    "Supplies & signage": ["Wayfinding and welcome signs", "Trash, recycling, restrooms", "Volunteer vests/badges"],
    "Auction / raffle items": ["Donor letters and tax receipts", "Item values and starting bids", "Display and checkout plan"],
    "Payment & admin fees": ["Card processing fees", "Ticketing platform terms", "Receipts for donors"],
    "Decor & signage": ["Branding and donation signage", "Table centerpieces", "Setup help"],
    "Facilitator / speaker": ["Fee, expenses, and agenda", "Materials they provide", "Cancellation terms"],
    "Materials & supplies": ["Quantity (+10% spare)", "Delivery date", "Handouts and name tags"],
    "Refreshments": ["Coffee/tea/water and snacks", "Dietary options", "Setup and cleanup"],
    "Entertainment & activities": ["Fit for the guests and the occasion", "Equipment and space needs", "Backup if they cancel"],
    "Decor & supplies": ["Theme palette and delivery vs DIY", "Setup and teardown help", "Venue rules on what you can hang or light"],
    "Marketing & invitations": ["Digital vs printed invitations", "RSVP or registration tracking", "Reminder schedule"],
    "Contingency": ["Hold back for surprises; track spend weekly"],
}

FALLBACK_IDEAS = {
    "birthday": [
        ("Signature activity station", "A DIY station matched to the honoree's interests (cookie decorating, crafts, trivia).", .06),
        ("Memory wall", "Guests add photos and notes to a wall or jar for the honoree to keep.", .02),
        ("Themed food table", "Build the menu around one theme with labeled dishes and a standout dessert.", .12),
        ("Group moment", "A scheduled toast, song or game so everyone shares the highlight.", .01),
    ],
    "community": [
        ("Local maker market corner", "Invite neighborhood crafters and food vendors for a small fee or donation.", .05),
        ("Kids' activity zone", "Chalk art, a scavenger hunt and a volunteer-run games table.", .04),
        ("Story or talent stage", "Open-mic slots for residents, with a short MC-led schedule.", .06),
        ("Neighbor connection board", "A board for skills, needs and volunteer sign-ups to extend the event's impact.", .01),
    ],
    "fundraiser": [
        ("Silent auction with local donors", "Businesses donate experiences; display with clear bid sheets.", .08),
        ("Matching-gift moment", "A sponsor pledges to match donations made during a set window.", .01),
        ("Impact story", "A beneficiary shares a short story before the ask.", .01),
        ("Raffle bundles", "Themed baskets sold in tiers to raise small donations.", .04),
    ],
    "workshop": [
        ("Hands-on first 15 minutes", "Start with an activity so attendees produce something early.", .02),
        ("Peer showcase", "End with 2-minute shares to cement learning.", .01),
        ("Take-home kit", "A one-page guide plus a small tool or template.", .05),
        ("Follow-up circle", "Create a group chat or monthly meetup for continued support.", .01),
    ],
    "other": [
        ("One signature moment", "Pick a single highlight (a toast, a reveal, a performance) and build the schedule around it.", .08),
        ("Welcome touch", "A greeter, a signature drink or a small keepsake as guests arrive.", .03),
        ("Shared memory table", "Photos, notes or a guest book that guests add to during the event.", .02),
        ("Easy interactive activity", "A low-effort game or station so guests mingle without needing instructions.", .05),
    ],
}


def kind(req: "PlanRequest") -> str:
    """Human-readable event type (uses the user's own words for 'other')."""
    if req.event_type == "other":
        return req.other_type.strip() or "event"
    return req.event_type


def cur(req: "PlanRequest") -> str:
    return req.currency.upper()


def build_budget(req: PlanRequest) -> dict:
    shares = BUDGET[req.event_type]
    items = []
    running = 0.0
    cats = list(shares)
    for i, cat in enumerate(cats):
        # last item takes the remainder so totals match to the cent
        amount = round(req.budget * shares[cat], 2) if i < len(cats) - 1 else round(req.budget - running, 2)
        running += amount
        items.append({"category": cat, "amount": amount, "percent": round(shares[cat] * 100)})
    return {"total": round(req.budget, 2), "per_guest": round(req.budget / req.guests, 2), "items": items}


def build_timeline(req: PlanRequest) -> dict:
    today = dt.date.today()
    event_date = req.date
    steps = TIMELINE[req.event_type]
    if event_date is None:
        return {"event_date": None, "compressed": False,
                "steps": [{"when": f"{d} days before" if d > 0 else ("Event day" if d == 0 else f"{-d} days after"),
                           "date": None, "task": t} for d, t in steps]}
    days_until = (event_date - today).days
    max_lead = max(d for d, _ in steps)
    # If there isn't enough runway, squeeze lead times proportionally.
    factor = 1.0 if days_until >= max_lead else max(days_until, 0) / max_lead
    out = []
    for d, task in steps:
        shifted = int(d * factor + 0.5) if d > 0 else d  # round half up (matches the in-page planner)
        when = event_date - dt.timedelta(days=shifted)
        out.append({"when": when.strftime("%a %b %d"), "date": when.isoformat(), "task": task})
    return {"event_date": event_date.isoformat(), "days_until": days_until,
            "compressed": factor < 1.0, "steps": out}


def build_vendors(budget: dict) -> list:
    return [{"category": it["category"], "budget": it["amount"],
             "checklist": VENDORS.get(it["category"], ["Get a written quote", "Confirm date and delivery"])}
            for it in budget["items"] if it["category"] != "Contingency"]


# ---- LLM personalization -----------------------------------------------------

def _prompt(req: PlanRequest, budget: dict) -> str:
    return f"""You are an experienced event planner. Personalize this {kind(req)} event.
Name: {req.name or 'unnamed'}; guests: {req.guests}; budget: {req.budget:,.0f} {cur(req)} ({budget['per_guest']:,.2f} {cur(req)}/guest);
location: {req.location or 'unspecified'}; setting: {req.indoor_outdoor};
honoree age: {req.honoree_age if req.honoree_age is not None else 'n/a'};
interests/vibe: {req.interests or 'none given'}; constraints: {req.notes or 'none'}.

Return ONLY a JSON object with keys:
"theme" (short string),
"summary" (2 sentences),
"ideas" (list of 5 objects: "title", "description", "est_cost" number in {cur(req)}, realistic and within budget),
"tips" (list of 3 short practical tips tailored to the constraints),
"invitation" (a warm 2-3 sentence invitation text)."""


async def llm_personalize(req: PlanRequest, budget: dict) -> Optional[dict]:
    payload = {"model": LLM_MODEL, "temperature": 0.7, "max_tokens": 1200,
               "response_format": {"type": "json_object"},
               "messages": [{"role": "user", "content": _prompt(req, budget)}]}
    try:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
            r = await client.post(f"{LLM_BASE_URL}/chat/completions", json=payload,
                                  headers={"Authorization": f"Bearer {LLM_API_KEY}"})
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
        match = re.search(r"\{.*\}", text, re.S)
        data = json.loads(match.group(0)) if match else None
        if not data or not isinstance(data.get("ideas"), list):
            return None
        ideas = []
        for idea in data["ideas"][:6]:
            if isinstance(idea, dict) and idea.get("title"):
                try:
                    cost = max(0.0, float(idea.get("est_cost", 0)))
                except (TypeError, ValueError):
                    cost = 0.0
                ideas.append({"title": str(idea["title"]), "description": str(idea.get("description", "")),
                              "est_cost": round(cost, 2)})
        if not ideas:
            return None
        return {"theme": str(data.get("theme", "")), "summary": str(data.get("summary", "")),
                "ideas": ideas, "tips": [str(t) for t in data.get("tips", [])][:5],
                "invitation": str(data.get("invitation", ""))}
    except Exception:
        return None


def fallback_personalize(req: PlanRequest, budget: dict) -> dict:
    flavor = req.interests.strip() or "a welcoming, easygoing"
    label = req.name or f"your {kind(req)}"
    ideas = [{"title": t, "description": d, "est_cost": round(req.budget * s, 2)}
             for t, d, s in FALLBACK_IDEAS[req.event_type]]
    tips = ["Confirm headcount one week out and plan for about 10% no-shows or extras.",
            "Book the highest-demand vendors first (venue, caterer, entertainment)."]
    if req.notes:
        tips.append(f"Build this into every vendor conversation: {req.notes[:120]}")
    if req.indoor_outdoor != "indoor":
        tips.append("For outdoor elements, keep a covered backup space or a weather date.")
    parts = [p.strip() for p in re.split(r"[,;]", req.interests) if p.strip()][:2]
    theme = " & ".join(parts)[:40].rstrip()
    theme = theme[:1].upper() + theme[1:] if theme else "Classic & cozy"
    return {"theme": theme,
            "summary": f"A {kind(req)} for {req.guests} guests with {req.budget:,.0f} {cur(req)} to spend "
                       f"(about {budget['per_guest']:,.2f} {cur(req)} per guest), "
                       + (f"built around {req.interests.strip()}." if req.interests.strip()
                          else "with a welcoming, easygoing feel."),
            "ideas": ideas, "tips": tips[:4],
            "invitation": f"You're invited to {label}! Join us for good company and a great time. "
                          f"Please RSVP so we can plan for everyone."}


# ---- Routes ---------------------------------------------------------------------

@app.post("/api/plan")
async def plan(req: PlanRequest):
    budget = build_budget(req)
    ai = await llm_personalize(req, budget)
    mode = "ai"
    if ai is None:
        ai, mode = fallback_personalize(req, budget), "offline"
    return {"mode": mode, "event_type": req.event_type, "event_label": kind(req), "currency": cur(req), "name": req.name,
            "personalized": ai, "budget": budget,
            "timeline": build_timeline(req), "vendors": build_vendors(budget)}


@app.get("/api/health")
async def health():
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            await client.get(f"{LLM_BASE_URL}/models", headers={"Authorization": f"Bearer {LLM_API_KEY}"})
        return {"ok": True, "llm": "reachable", "model": LLM_MODEL}
    except Exception:
        return {"ok": True, "llm": "unreachable (offline fallback active)", "model": LLM_MODEL}


@app.get("/")
async def index():
    return FileResponse(HERE / "index.html")
