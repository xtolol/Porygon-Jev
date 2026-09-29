# Jev Showdown Lab

An experimental Python project investigating whether [TypeSafe AI's Jev](https://docs.typesafe.ai/) can act as a decision policy for turn-based Pokémon Showdown battles.

The project uses [poke-env](https://poke-env.readthedocs.io/) to connect agents to a local Pokémon Showdown server, convert live battles into JSON-compatible snapshots, present legal actions to Jev through TypeSafe's API, execute the selected action, and record decision telemetry.

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

### Switching memory (v0.3b)

Each legal switch carries type matchups, visible entry hazards, boosts lost on switching, the count of consecutive voluntary switches, and the most recent observed move when its user matches the current active opponent. The type matchups and possible STAB are typing evidence, not damage estimates or predictions.

`recent_actions` holds up to three of our resolved selections. A switch entry includes its source, destination, whether the selection was forced, and the selected Pokémon's HP before and after the turn. That HP difference is a net observation and may include hazards, healing, or other effects. `recent_opponent_actions` holds up to six observed opponent move and switch events from Showdown's battle messages; repeated uses remain separate events. Both histories are scoped to one battle and cleared when it finishes. The decision schema is 6 and the telemetry record schema is 8.

## Requirements

- Python 3.12
- Node.js 22 or newer
- A local Pokémon Showdown server
- A TypeSafe API key
- macOS, Windows or Linux

The package currently supports Python:

```text
>=3.12,<3.14
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
cp config/config-example.js config/config.js
```

Start it on the default port 8000 with guest authentication disabled for
local bot battles:

```bash
node pokemon-showdown start --no-security
```

Keep the server terminal open while running the Python agent.

Confirm that it is listening on macOS:

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
```

The project's `LOCAL_SERVER` configuration points to:

```text
ws://127.0.0.1:8000/showdown/websocket
```

The example players use generated guest names and no Showdown passwords. Without
`--no-security`, Showdown rejects their empty authentication assertions with
`Your authentication token was invalid`. Restart the server with this flag
before retrying the battle. Use it only on a private local development server.

## TypeSafe API configuration

Create an API key in your TypeSafe account.

Set it for the current macOS or Linux terminal:

```bash
export TYPESAFE_API_KEY="your-api-key"
```

On Windows PowerShell:

```powershell
$env:TYPESAFE_API_KEY="your-api-key"
```

Never commit the key to the repository.

The policy calls:

```text
POST https://api.typesafe.ai/v1/systemone
```

using the model:

```text
jev-latest
```

Each request contains:

- A structured battle state.
- A bounded choice question.
- One criterion for every legal action.

Jev returns a selected option, probability distribution and confidence value.

Check TypeSafe's API documentation and account dashboard for current model availability and rate limits before running large experiments.

## Running a battle

Start the local Showdown server first, then activate the Python environment:

```bash
source .venv/bin/activate
```

Run the Jev battle example from the `jev-showdown-lab` directory:

```bash
python examples/jev_battle.py
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

The TypeSafe API may return transient errors such as:

- `429 Too Many Requests`
- `502 Bad Gateway`
- `503 Service Unavailable`
- `504 Gateway Timeout`
- `529 Overloaded`

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
- [TypeSafe API reference](https://docs.typesafe.ai/api)
- [TypeSafe models](https://docs.typesafe.ai/models)
- [TypeSafe AI](https://typesafe.ai/)
