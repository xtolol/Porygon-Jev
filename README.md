# Jev Showdown Lab

An experimental Python project investigating whether [TypeSafe AI's Jev](https://vercel.com/ai-gateway/models/jev) can act as a decision policy for turn-based Pokémon Showdown battles.

The project uses [poke-env](https://poke-env.readthedocs.io/) to connect agents to a local Pokémon Showdown server, convert live battles into JSON-compatible snapshots, present legal actions to Jev through Vercel AI Gateway, execute the selected action, and record decision telemetry.

## Project status

This is an early viability prototype rather than a competitive Pokémon agent.

The current implementation can:

- Connect two poke-env agents to a local Pokémon Showdown server.
- Convert battle, Pokémon, move, field and action state into immutable snapshots.
- Enumerate legal moves and switches.
- Send the current state and legal actions to Jev.
- Map Jev’s selected action back to a live poke-env battle order.
- Retry transient AI Gateway failures.
- Fall back to another policy when configured.
- Record each decision and its selection source.
- Run local battles against `RandomPlayer`.

Preliminary experiments suggest that Jev handles straightforward damage-oriented positions reasonably well but currently struggles with longer-term strategies such as recovery and Toxic stall. These observations are exploratory and are not yet statistically meaningful benchmarks.

## Architecture

```text
Pokémon Showdown
        │
        ▼
     poke-env
        │
        ▼
Live Battle object
        │
        ▼
DecisionSnapshot
├── BattleStateSnapshot
├── Pokémon snapshots
├── Move snapshots
└── Legal ActionOptions
        │
        ▼
Jev selection policy
        │
        ▼
Selected action ID
        │
        ▼
Live Move or Pokémon
        │
        ▼
poke-env BattleOrder
        │
        ▼
Decision telemetry
```

Jev receives snapshots rather than live poke-env objects. Its result is validated against the legal actions before being converted back into a Showdown order.

## Requirements

- Python 3.12
- Node.js 22 or newer
- A local Pokémon Showdown server
- A Vercel AI Gateway API key
- macOS, Windows or Linux

The project currently expects Python:

```text
>=3.12,<3.13
```

## Python installation

Clone the repository and enter its root directory:

```bash
git clone <repository-url>
cd jev-showdown-lab
```

Create and activate a virtual environment on macOS or Linux:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

On Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
```

Install the project and its dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -e .
```

## Local Pokémon Showdown server

Clone Pokémon Showdown separately:

```bash
git clone https://github.com/smogon/pokemon-showdown.git
cd pokemon-showdown
npm ci
```

Start it on port 8080:

```bash
./pokemon-showdown start 8080
```

Alternatively:

```bash
node pokemon-showdown start 8080
```

Keep the server terminal open while running the Python agent.

Confirm that it is listening on macOS:

```bash
lsof -nP -iTCP:8080 -sTCP:LISTEN
```

The poke-env configuration should point to:

```text
ws://127.0.0.1:8080/showdown/websocket
```

## Vercel AI Gateway configuration

Create an AI Gateway API key through the Vercel dashboard.

Set it for the current macOS or Linux terminal:

```bash
export AI_GATEWAY_API_KEY="your-api-key"
```

On Windows PowerShell:

```powershell
$env:AI_GATEWAY_API_KEY="your-api-key"
```

Never commit the key to the repository.

The policy calls:

```text
POST https://ai-gateway.vercel.sh/v1/evaluate
```

using the model:

```text
typesafe-ai/jev
```

Each request contains:

- A structured battle state.
- A bounded choice question.
- One criterion for every legal action.

Jev returns a selected option, probability distribution and confidence value.

AI Gateway pricing, availability and rate limits can change. Check the Vercel dashboard and current model page before running large experiments.

## Running a battle

Start the local Showdown server first, then activate the Python environment:

```bash
source .venv/bin/activate
```

Run the battle example from the repository root:

```bash
python examples/hello_battle.py
```

The terminal should display selections resembling:

```text
Jev selected: move:2:thunderbolt
Confidence: 0.72
Selected action: move:2:thunderbolt | source: jev
```

Possible selection sources include:

```text
jev
random_fallback
heuristic_fallback_429
heuristic_fallback_503
```

## Decision telemetry

Each decision record associates the state observed by the policy with the action that was actually executed.

Useful telemetry includes:

- Battle identifier.
- Turn number.
- Legal actions.
- Selected action ID.
- Jev-selected action ID.
- Selection source.
- Jev probabilities.
- Jev confidence.
- Request attempt count.
- HTTP status codes.
- Request latency.
- Model identifier.
- Gateway generation identifier.

Selection source is especially important. A battle containing fallback decisions should not be reported as a pure Jev-controlled battle.

## Reliability

AI Gateway may return transient errors such as:

- `429 Too Many Requests`
- `502 Bad Gateway`
- `503 Service Unavailable`
- `504 Gateway Timeout`

The policy should:

1. Serialize requests through a shared asynchronous client.
2. Respect `Retry-After` when supplied.
3. Use exponential backoff.
4. Avoid unlimited rapid retries.
5. Clearly record any fallback action.

For untimed local experiments, the policy can wait until Jev succeeds. For practical or timed battles, use bounded retries followed by a deterministic fallback.

## Current observations

A small best-of-three experiment against `RandomPlayer` produced two Jev wins and one loss.

The wins were decisive when high-powered attacks could immediately knock out opposing Pokémon. The loss exposed a longer-horizon weakness: a Mandibuzz using Toxic and Roost repeatedly recovered damage while residual poison wore down five of Jev’s Pokémon.

This suggests that the current policy is effective at obvious immediate choices but lacks sufficient Pokémon-specific tactical context and temporal reasoning. Three battles are not enough to establish a reliable win rate.

## Development roadmap

Context will be introduced incrementally so that its effect can be measured.

### V1 — Raw context

- Current snapshot models
- Legal moves and switches
- Jev choice probabilities
- Confidence and selection-source telemetry

### V2 — Type context

- Type effectiveness
- STAB
- Immunity and resistance labels

### V3 — Effective power

- Accuracy-adjusted effective power
- Explicit comparison between attacking options

### V4 — Damage context

- Estimated damage range
- Expected damage fraction
- Knockout potential

### V5 — Turn order

- Effective speed
- Move priority
- Likely first mover

### V6 — Switching

- Entry-hazard damage
- Defensive matchup
- Offensive matchup after switching

### V7 — Strategic moves

- Recovery
- Status effects
- Stat boosts
- Hazards
- Protect-like moves
- Pivoting and forced switching

### V8 — Temporal context

- Recent actions
- HP changes
- Repeated actions
- Progress across turns
- Recovery and residual-damage patterns

### V9 — Lookahead

- Plausible opponent responses
- Best- and worst-case outcomes
- Short rollout summaries
- Jev selection over evaluated future positions

Each version should be benchmarked independently instead of introducing every feature simultaneously.

## Evaluation plan

Initial opponents should include:

- `RandomPlayer`
- A maximum-base-power player
- `SimpleHeuristicsPlayer`
- Scripted matchup agents such as recovery or Toxic stall

Recommended metrics include:

- Win rate.
- Pure-Jev win rate.
- Jev decision coverage.
- Fallback rate.
- Average attempts per decision.
- `429` and `503` rates.
- Median and p95 request latency.
- Average confidence.
- Probability margin.
- Invalid selections.
- Decision performance by turn.

A small number of battles is useful for debugging, but meaningful comparisons require substantially more games and consistent configurations.

## Limitations

- Jev is a hosted, stateless decision model.
- Battle experience does not update Jev’s weights.
- The current context does not yet include damage calculation or lookahead.
- Random battles introduce substantial team and matchup variance.
- API availability can affect which policy actually controls a turn.
- Jev confidence is not the probability that an action will win the battle.
- Opponent information must remain limited to public or revealed information.
- The project currently focuses on singles battles.

## Long-term direction

The intended long-term architecture combines:

- Jev as a fast structured-action selector.
- Pokémon-specific derived features.
- A shallow lookahead system.
- Persistent battle telemetry.
- A locally trained value or reinforcement-learning policy.

Jev could eventually act as a prior, teacher or high-level selector while a local model learns Pokémon-specific action values from battle outcomes.

## References

- [poke-env documentation](https://poke-env.readthedocs.io/)
- [Pokémon Showdown](https://github.com/smogon/pokemon-showdown)
- [Vercel AI Gateway evaluation API](https://vercel.com/docs/ai-gateway/modalities/evaluation)
- [Jev on Vercel AI Gateway](https://vercel.com/ai-gateway/models/jev)
- [TypeSafe AI](https://typesafe.ai/)