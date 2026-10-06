# Project 3: Marriage Market

Simulator for COMS W4444, Fall 2026.

## Setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then:

```
uv run main.py
```

## CLI Arguments

| Argument | Default | Description |
| --- | --- | --- |
| `--player CODE COUNT` | `g 10` + `r 10` | Add COUNT people running player CODE. Repeatable. N is the total and must be even. |
| `-t`, `--rounds` | `100` | Rounds of dating, t. |
| `-B`, `--bonus` | `100` | Marriage bonus B. |
| `-d`, `--dims` | `5` | Profile dimensions, d. |
| `-m`, `--monotonic` | `2` | Number of monotonic dimensions, m <= d. They are the first m dimensions. |
| `--dist` | `mixed` | Preset distribution P: `uniform`, `normal`, or `mixed`. |
| `--dist-file PATH` | none | JSON file holding P as d rows of 11 probabilities (values 0-10). Overrides `--dist`. |
| `--seed` | `4444` | Random seed, for repeatable runs. |
| `--timeout` | `1.0` | Per-call wall-clock budget for player code, in seconds. `0` disables. Relies on `SIGALRM`; a no-op on Windows. |
| `--log PATH` | `logs/marriage-*.log` | Per-round debug log (interest lists, dates, decisions, marriages, faults). |
| `--no-log` | off | Do not write a debug log. |
| `--summary-only` | off | Drop each round's `RoundRecord` once played. Results are unchanged; long runs stop holding one record per round. |
| `--gui` | off | Launch the visualizer. Without it, results print as JSON. |

Player codes are discovered automatically: `r` for the random baseline, `g` for
the greedy baseline, and any `player_<k>` directory (code `k`, no cap on how
many groups).

```
uv run main.py --player g 10 --player 4 10 --rounds 50 --bonus 200 --seed 7
```

The presets for P are:

- `uniform`: every value 0-10 equally likely, in every dimension.
- `normal`: a discretised normal centred on 5 (sd 2), in every dimension.
- `mixed`: monotonic dimensions are normal, so most people are middling and
  a 10 is rare. The remaining dimensions alternate between uniform and normal.

A `--dist-file` is either a bare list of d rows, or `{"P": [...]}`. Each row
has 11 probabilities, for values 0 through 10, and must sum to 1.

## Visualizer

```
uv run main.py --gui --player g 10 --player r 10
```

Everybody sits on a ring, coloured by the group whose code runs them. Each
round's dates are drawn as chords coloured by how the simulator paired them:
repeat, mutual interest, one-sided interest, or random. A pink dot marks a
proposal that was not returned. Married couples are joined in gold for the
rest of the run. Click a person to see their true profile, ideal,
advertisement, and dating history. That is engine truth, which no player ever
sees. A player fault gets a red banner across the top of the window.

| Key | Action |
| --- | --- |
| `SPACE` | Play / pause |
| `RIGHT` or `S` | Next round |
| `UP` / `DOWN` | Faster / slower (1-32 rounds per second) |
| Click | Select a person (click empty space to clear) |
| `Q` or `ESC` | Quit |

The **Skip to round** box under the header is how you jump: type a round
number and press Enter. It cannot rewind.

Every `main.py` run writes a debug log under `logs/`. Use `--log PATH` to
choose the file or `--no-log` to skip it. The log starts with everyone's true
profile, ideal, and advertisement. Each round then lists who asked for whom,
every date (what each side projected, the ideal each side described, and
what each decided), marriages, and faults. It ends with a JSON snapshot of the
results.

## Sweeps and the tournament

```
uv run sweep.py configs/bonus_sweep.json
uv run sweep.py configs/distribution_comparison.json --rounds 50 --seeds 1 2 3
uv run tournament.py configs/tournament.json
uv run tournament.py configs/tournament.json --rank-by mean_happiness --live
uv run tournament.py configs/tournament.json --gui
```

A sweep runs each configuration in a config file over a set of seeds. It
prints mean happiness, the share of people with positive happiness, the share
who married, and the average round they married on. Full JSON and CSV output
goes to `results/`. `configs/bonus_sweep.json` is the handout's "if B is very
high, what will happen?" question.

The tournament ranks groups across many markets. Each group gets a market
where it holds every seat, a half-and-half market with every other group,
and (with three or more groups) one market with everybody mixed in. There is
no scoring rule inside a single run. Groups are ranked by the share of their
seats that ended with positive happiness (the primary goal), with mean
happiness (the secondary goal) as the tie-break.

## Writing a player

Every `4` below is just an example. Replace it with your own group number
everywhere: the directory name, the class name, and the `--player` code. If
you are group 7, you use `player_7`, `Player7`, and `--player 7`.

Copy the template directory, renaming it for your group number, and rename the
class inside it to match. Group 4 would run:

```
cp -r players/player_template players/player_4
```

and edit `players/player_4/player.py` so the class is named `Player4`. Your
group directory ends up as:

```
players/player_4/
  __init__.py     required - see below
  player.py       class Player4(BasePlayer)
```

Then run it with `--player 4 <count>`:

```
uv run main.py --player 4 10 --player g 10
```

`players/player_template/player.py` documents the full interface inline:
what you can see, what you cannot, and what happens when your code
misbehaves. The minimum is `choose_dates` and `decide`:

```python
from models.player import Player as BasePlayer, Decision


class Player4(BasePlayer):
	def choose_dates(self, candidates, turn):
		return [c.index for c in candidates]

	def decide(self, date, observed, stated_ideal):
		return Decision(again=True, propose=date.date_number >= 2)
```

Three things that will make your player fail to appear, none of which produce a
loud error:

- **A missing `__init__.py`.** Discovery uses `pkgutil.iter_modules`, which
  only reports directories that have one. Without it your group is not
  reported as broken, it is not seen at all. The template ships with one.
- **A directory name that is not `player_<digits>`.** `player_4` works,
  `player_four` and `group4` do not.
- **A class named anything but `Player<k>`.** `Player4` works;
  `MyGreatMatchmaker` gets reported as an `AttributeError` at startup.

Anything that fails to import is printed as a warning and skipped, so a broken
commit from your group never stops anyone else's run. Check for your code in
the startup warnings before assuming it ran.

### The interface

One instance of your class is one person. Your code may run several people in
the same market, possibly all of them, one instance each. Do not share state
between instances (class attributes, module globals, files). The handout
forbids it.

On `self` you get your own `profile` (T_p) and `ideal` (D_p), your `index`,
and the public parameters `people` (N), `dims` (d), `monotonic` (m), `rounds`
(t) and `bonus` (B). You do not get P, and you never see anyone else's true
profile.

| Method | When | Return |
| --- | --- | --- |
| `advertise()` | Once, before round 1. Fixed for the whole run. | `Advertisement(own_dim, own_value, seek_dim, seek_value)` - need not be true. Default: honest, dimension 0. |
| `choose_dates(candidates, turn)` | Each round you are single and not on a repeat date. | Any subset of `candidate.index` values. |
| `project(date)` | Start of each date. | The profile your behaviour projects. Default: your true profile. |
| `describe_ideal(date, observed)` | End of each date, after seeing their projection. | The ideal partner you describe. Default: your true ideal. |
| `decide(date, observed, stated_ideal)` | After both sides describe. | `Decision(again, propose, incompatible)`. |
| `on_outcome(outcome)` | After both sides decide. | Nothing. Tells you if they proposed, if you married, and if you both asked again. |

Each `Candidate` carries the person's `index`, their `ad`, and how many
`dates` you two have had. You are never offered someone you marked
incompatible. You are not told if someone marked *you* incompatible, but the
simulator will never pair you with them. `DateContext.date_number` counts the
current date, so it is 2 on the first date at which a proposal is legal.

If you build contexts for your own tests, import them from `models.player`.
The happiness arithmetic is importable too, from `models.profile`
(`decrement`, `happiness`).

### What the simulator enforces

- **Time limit.** Every call gets `--timeout` seconds. Exceed it and you
  forfeit that move. The limit is enforced with `SIGALRM`, which is Unix-only
  and main-thread-only. On Windows there is no alarm to set, so `--timeout`
  is a no-op and a slow player runs to completion rather than being cut off.
  Your code still has to finish quickly, because the tournament runs on Unix,
  where the limit is real. `--timeout 0` disables it everywhere.
- **Validity.** Profiles must be exactly d plain `int`s in 0-10. `numpy`
  integers are rejected, and the fault names the type. Decision flags must be
  real `bool`s. A proposal before the second date, or `incompatible`
  combined with `again` or `propose`, is rejected. So is naming somebody who
  is not among this round's candidates.
- **Fallbacks.** A forfeited move gets a safe default. `project` and
  `describe_ideal` fall back to the truth, `choose_dates` to nobody,
  `decide` to `Decision()` (no again, no proposal, nothing blocked), and
  `advertise` to an honest ad on dimension 0. Every forfeit is recorded in the
  `faults` list in the results.
- **Isolation.** Exceptions in your code forfeit your move only. A
  constructor that raises leaves you in the market on fallbacks for the whole
  run. A module that fails to import is reported at startup and skipped, so
  a broken commit from one group does not stop anyone else's.

## Submitting your player

**Fork this repository**, then open a pull request back into `main`. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the exact steps and rules. You only
ever touch `players/player_4/`, never anyone else's folder or the simulator
core. As before, `4` is just an example. Use your actual group number
throughout.

```
# on your fork
cp -r players/player_template players/player_4
# edit players/player_4/player.py  →  class Player4

git add players/player_4
git commit -m "Group 4: <what changed>"
git push
```

Open the PR against this repo's `main`, name it with your group number, and
one of us will review and merge it. Once merged, `players/player_4/` lives on
`main` alongside everyone else's. That is expected, not a leak: other groups
can see your merged code, the same way this course's simulators have always
worked. Logs under `logs/` are only on the machine that ran the sim; they are
not a submission.

## Rules implemented

Each person has a true profile T_p and a desired profile D_p. Each is d
integers from 0 to 10, drawn independently from the distribution P.

**Advertising.** Before round 1, each person posts one of their own
characteristics and one desired characteristic. The ad is fixed for the whole
simulation and need not be true.

**Pairing.** Each round, every single person is paired in this order:

1. Pairs where both people asked for another date at the end of their last
   date are paired first.
2. Everyone else names the people they would like to date. Pairs who named
   each other are paired at random.
3. Of the rest, pairs where one person named the other are paired at random.
4. Anyone left is paired at random.

A person who has marked someone incompatible is never paired with them again,
in either direction. In rare cases this leaves a person without a date for a
round.

**Dates.** During a date each person projects a profile, which need not be
their true one. Their date senses exactly that projection. At the end, each
describes the ideal partner they are seeking, honestly or not. Then each
decides whether to ask for another date, propose, or mark the other
incompatible.

**Marriage.** A proposal is only allowed from the second date with the same
person onward. If both propose on the same date, they are married and leave
the pool. If only one proposes, the recipient is told, and dating continues.
The run ends after t rounds, or earlier once fewer than two people are single.

**Happiness**, scored on true profiles only:

- An unmarried person scores 0.
- A married person scores B, minus their own decrement, minus half of their
  partner's decrement.
- A decrement compares what a person wanted (w) against their partner's true
  value (v) in each dimension. For the first m (monotonic) dimensions, it adds
  (w - v)² only when w > v. Meeting or beating what was wanted costs nothing.
  For every other dimension it adds (w - v)².

Primary goal: end with positive happiness as often as possible. Secondary
goal: maximise your player's average happiness.

## Checks before you push

```
uv run ruff format
```
Auto-formats your code to match the project style.

```
uv run ruff check --fix
```
Lints your code and auto-fixes what it safely can.

```
uv run pytest
```
Runs the test suite.
