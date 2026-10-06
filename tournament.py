"""Tournament runner: rank groups by how their people do across many markets.

There is no scoring rule *within* a single simulation. A run produces a
happiness for each person, and that is all it produces - no winner, no points.
Groups are ranked by averages across many runs, in many different mixes of
groups sharing a market. A group whose people consistently marry badly shows
up in every configuration it appears in, without anyone having to invent a
formula for a single run.

Rosters are built three ways, because N people per market is far too many
seats to enumerate every combination of groups:

    solo   every seat runs the same group - the handout's "perhaps all of them"
    pairs  every pair of groups, half the seats each
    mix    every group at once, seats dealt round-robin (three or more groups)

    uv run tournament.py configs/tournament.json
    uv run tournament.py configs/tournament.json --rank-by mean_happiness --live

The primary goal in the handout is a positive happiness as often as possible,
so ``positive_rate`` is the default ranking; ``mean_happiness`` is the
secondary goal and the tie-break.

Everything about running jobs is borrowed from sweep.py rather than
reimplemented: the process pool, the progress line, the deterministic sort and
the per-cell statistics all come from there.
"""

import argparse
import csv
import json
import multiprocessing as mp
import random
import sys
from collections import defaultdict
from dataclasses import dataclass, replace
from itertools import combinations, product
from pathlib import Path

from core.engine import Engine
from core.registry import discover
from sweep import execute, execute_live, summarise

GROUP_METRICS = ('positive_rate', 'mean_happiness', 'married_rate')
ROSTER_KINDS = ('solo', 'pairs', 'mix')

DEFAULTS = {
	'people': 20,
	'rounds': 100,
	'bonus': 100.0,
	'dims': 5,
	'monotonic': 2,
	'distribution': 'mixed',
	'timeout': 1.0,
}


@dataclass(frozen=True)
class Arena:
	"""One set of market parameters. Every roster plays every arena."""

	people: int
	rounds: int
	bonus: float
	dims: int
	monotonic: int
	distribution: str
	timeout: float

	@property
	def label(self) -> str:
		return (
			f'N{self.people} d{self.dims} m{self.monotonic} t{self.rounds} '
			f'B{self.bonus:g} {self.distribution}'
		)


@dataclass(frozen=True)
class Match:
	"""One roster in one arena, to be run over every seed."""

	arena: Arena
	kind: str
	roster: tuple[str, ...]

	@property
	def roster_text(self) -> str:
		counts: dict[str, int] = {}
		for code in self.roster:
			counts[code] = counts.get(code, 0) + 1
		return '+'.join(f'{code}x{n}' for code, n in sorted(counts.items()))

	@property
	def label(self) -> str:
		return f'{self.roster_text} @ {self.arena.label}'


# ----------------------------------------------------------------- config


def load_config(path: Path | str) -> dict:
	path = Path(path)
	raw = json.loads(path.read_text())
	defaults = {**DEFAULTS, **raw.get('defaults', {})}

	grid = raw.get('grid') or {}
	keys = sorted(grid)
	arenas: list[Arena] = []
	for combo in product(*(grid[k] for k in keys)) if keys else [()]:
		merged = {**defaults, **dict(zip(keys, combo, strict=True))}
		arenas.append(
			Arena(
				people=int(merged['people']),
				rounds=int(merged['rounds']),
				bonus=float(merged['bonus']),
				dims=int(merged['dims']),
				monotonic=int(merged['monotonic']),
				distribution=str(merged['distribution']),
				timeout=float(merged['timeout']),
			)
		)

	kinds = list(raw.get('rosters', ROSTER_KINDS))
	unknown = [k for k in kinds if k not in ROSTER_KINDS]
	if unknown:
		raise ValueError(f'unknown roster kinds {unknown}; choose from {list(ROSTER_KINDS)}')

	return {
		'name': str(raw.get('name') or path.stem),
		'description': str(raw.get('description', '')),
		'source': str(path),
		'seeds': [int(s) for s in raw.get('seeds', [4444])],
		'entrants': raw.get('entrants'),
		'rosters': kinds,
		'arenas': arenas,
	}


def entrants_for(config: dict) -> list[str]:
	"""Which player codes compete. Defaults to everything the registry loaded."""
	available, errors = discover()
	for err in errors:
		print(f"warning: player '{err.code}' failed to load - {err.message}", file=sys.stderr)

	if config['entrants']:
		missing = [c for c in config['entrants'] if c not in available]
		if missing:
			raise SystemExit(f'entrants not loadable: {missing}. Available: {sorted(available)}')
		return sorted(config['entrants'])

	return sorted(available)


def build_matches(config: dict, entrants: list[str]) -> tuple[list[Match], list[str]]:
	matches: list[Match] = []
	skipped: list[str] = []

	for arena in config['arenas']:
		n = arena.people
		if n < 2 or n % 2:
			skipped.append(f'{arena.label}: N must be even and at least 2')
			continue
		if 'solo' in config['rosters']:
			for code in entrants:
				matches.append(Match(arena=arena, kind='solo', roster=(code,) * n))
		if 'pairs' in config['rosters']:
			for a, b in combinations(entrants, 2):
				roster = (a,) * (n // 2) + (b,) * (n - n // 2)
				matches.append(Match(arena=arena, kind='pairs', roster=roster))
		if 'mix' in config['rosters'] and len(entrants) >= 3:
			roster = tuple(entrants[i % len(entrants)] for i in range(n))
			matches.append(Match(arena=arena, kind='mix', roster=roster))

	return matches, skipped


# ----------------------------------------------------------------- running


def _run_match(job: dict) -> dict:
	"""Play one roster in one arena at one seed, in a worker process."""
	available, _ = discover()
	roster = [available[code] for code in job['roster']]

	# RandomPlayer draws from the global module rather than the engine's rng.
	# Seeding here is what makes a tournament re-runnable.
	random.seed(job['seed'])

	results = Engine(
		players=roster,
		rounds=job['rounds'],
		bonus=job['bonus'],
		dims=job['dims'],
		monotonic=job['monotonic'],
		seed=job['seed'],
		distribution=job['distribution'],
		timeout=job['timeout'],
		keep_records=False,
	).run()

	return {
		'cell': job['cell'],
		'seed': job['seed'],
		'roster': list(job['roster']),
		'married_rate': results['married_rate'],
		'positive_rate': results['positive_rate'],
		'mean_happiness': results['mean_happiness'],
		'faults': len(results['faults']),
		'seats': [
			{
				'code': job['roster'][p['index']],
				'index': p['index'],
				'happiness': p['happiness'],
				'positive': p['positive'],
				'married': p['married'],
				'married_on': p['married_on'],
			}
			for p in results['players']
		],
	}


def build_jobs(matches: list[Match], seeds: list[int]) -> list[dict]:
	jobs = []
	for i, match in enumerate(matches):
		for seed in seeds:
			jobs.append(
				{
					'cell': i,
					'seed': seed,
					'roster': match.roster,
					'rounds': match.arena.rounds,
					'bonus': match.arena.bonus,
					'dims': match.arena.dims,
					'monotonic': match.arena.monotonic,
					'distribution': match.arena.distribution,
					'timeout': match.arena.timeout,
				}
			)
	return jobs


# ----------------------------------------------------------------- ranking


def rank(matches: list[Match], runs: list[dict], entrants: list[str], rank_by: str) -> dict:
	"""Average each group over every seat it held, in every run.

	Seats rather than runs, so a group holding all twenty seats in a solo
	market counts twenty times as much as it does holding one: it really did
	take every seat, and every consequence of that is its own.
	"""
	seats: dict[str, dict[str, list[float]]] = {
		code: {m: [] for m in GROUP_METRICS} for code in entrants
	}
	appearances: dict[str, int] = defaultdict(int)
	faults: dict[str, int] = defaultdict(int)

	for run in runs:
		for seat in run['seats']:
			bucket = seats[seat['code']]
			bucket['positive_rate'].append(1.0 if seat['positive'] else 0.0)
			bucket['mean_happiness'].append(seat['happiness'])
			bucket['married_rate'].append(1.0 if seat['married'] else 0.0)
		for code in set(run['roster']):
			appearances[code] += 1
			faults[code] += run['faults']

	table = []
	for code in entrants:
		if not seats[code]['mean_happiness']:
			continue
		row = {
			'code': code,
			'runs': appearances[code],
			'seats': len(seats[code]['mean_happiness']),
		}
		for metric in GROUP_METRICS:
			row[metric] = summarise(seats[code][metric])
		table.append(row)

	table.sort(key=lambda r: (-r[rank_by]['mean'], -r['mean_happiness']['mean'], r['code']))
	for position, row in enumerate(table, start=1):
		row['rank'] = position

	return {
		'ranked_by': rank_by,
		'standings': table,
		'matches': [
			{'label': m.label, 'kind': m.kind, 'roster': m.roster_text, 'arena': m.arena.label}
			for m in matches
		],
	}


# ----------------------------------------------------------------- output


def write_outputs(report: dict, out_dir: Path) -> list[Path]:
	out_dir.mkdir(parents=True, exist_ok=True)
	stem = report['tournament']

	json_path = out_dir / f'{stem}.json'
	json_path.write_text(json.dumps(report, indent=2) + '\n')

	standings_path = out_dir / f'{stem}_standings.csv'
	header = ['rank', 'code', 'runs', 'seats']
	for metric in GROUP_METRICS:
		header += [f'{metric}_{stat}' for stat in ('mean', 'median', 'stddev')]
	with standings_path.open('w', newline='') as fh:
		writer = csv.writer(fh)
		writer.writerow(header)
		for row in report['standings']:
			line = [row['rank'], row['code'], row['runs'], row['seats']]
			for metric in GROUP_METRICS:
				line += [row[metric][s] for s in ('mean', 'median', 'stddev')]
			writer.writerow(line)

	runs_path = out_dir / f'{stem}_runs.csv'
	with runs_path.open('w', newline='') as fh:
		writer = csv.writer(fh)
		writer.writerow(
			[
				'match',
				'kind',
				'arena',
				'seed',
				'seat_index',
				'code',
				'happiness',
				'positive',
				'married',
				'married_on',
				'faults',
			]
		)
		for run in report['runs']:
			match = report['matches'][run['cell']]
			for seat in run['seats']:
				writer.writerow(
					[
						match['roster'],
						match['kind'],
						match['arena'],
						run['seed'],
						seat['index'],
						seat['code'],
						seat['happiness'],
						int(seat['positive']),
						int(seat['married']),
						'' if seat['married_on'] is None else seat['married_on'],
						run['faults'],
					]
				)

	return [json_path, standings_path, runs_path]


def print_standings(report: dict) -> None:
	print(f'\n{report["tournament"]}  -  ranked by {report["ranked_by"]}')
	print(
		f'{"#":>2}  {"group":<6}  {"runs":>5}  {"seats":>6}  '
		f'{"positive":>9}  {"happiness":>16}  {"married":>8}'
	)
	for row in report['standings']:
		happy = row['mean_happiness']
		print(
			f'{row["rank"]:>2}  {row["code"]:<6}  {row["runs"]:>5}  {row["seats"]:>6}  '
			f'{100 * row["positive_rate"]["mean"]:>8.1f}%  '
			f'{happy["mean"]:>9,.1f} +/-{happy["stddev"]:>4,.0f}  '
			f'{100 * row["married_rate"]["mean"]:>7.1f}%'
		)


def print_live_board(
	name: str,
	matches: list[Match],
	entrants: list[str],
	runs: list[dict],
	rank_by: str,
	done: int,
	total: int,
) -> None:
	"""Redraw a text leaderboard after every finished run."""
	sys.stdout.write('\033[2J\033[H')
	print(f'{name}  LIVE  {done}/{total} runs')
	print('Order can jump until every mix has finished.\n')
	if not runs:
		print('  waiting for the first match...')
		sys.stdout.flush()
		return
	partial = {'tournament': name, **rank(matches, runs, entrants, rank_by)}
	print_standings(partial)
	seen = {row['code'] for row in partial['standings']}
	for code in entrants:
		if code not in seen:
			print(f'     {code:<6}  (no results yet)')
	sys.stdout.flush()


# ----------------------------------------------------------------- cli


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
	parser = argparse.ArgumentParser(description='Rank groups across many shared markets.')
	parser.add_argument(
		'config', type=Path, help='Tournament description, e.g. configs/tournament.json'
	)
	parser.add_argument('--out-dir', type=Path, default=Path('results'))
	parser.add_argument('--seeds', type=int, nargs='+', help='Override the seed list.')
	parser.add_argument('--rounds', type=int, help='Override t for every arena.')
	parser.add_argument('--bonus', type=float, help='Override B for every arena.')
	parser.add_argument(
		'--entrants', nargs='+', help='Restrict to these player codes instead of everything loaded.'
	)
	parser.add_argument(
		'--rank-by',
		default='positive_rate',
		choices=GROUP_METRICS,
		help='Which average to sort the standings on, highest first. Ties fall back to '
		'mean_happiness.',
	)
	parser.add_argument(
		'--gui',
		action='store_true',
		help='Open a leaderboard window that updates as matches finish.',
	)
	parser.add_argument(
		'--live',
		action='store_true',
		help='Redraw a text leaderboard after every finished run. No GUI.',
	)
	parser.add_argument('--workers', type=int, default=0)
	return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
	args = parse_args(argv)
	if not args.config.exists():
		raise SystemExit(f'no such config: {args.config}')

	config = load_config(args.config)
	if args.seeds:
		config['seeds'] = args.seeds
	if args.entrants:
		config['entrants'] = args.entrants
	changes = {k: getattr(args, k) for k in ('rounds', 'bonus') if getattr(args, k) is not None}
	if changes:
		config['arenas'] = [replace(a, **changes) for a in config['arenas']]

	entrants = entrants_for(config)
	matches, skipped = build_matches(config, entrants)
	for note in skipped:
		print(f'warning: skipping {note}', file=sys.stderr)
	if not matches:
		raise SystemExit('no legal matches: check that N is even')

	jobs = build_jobs(matches, config['seeds'])
	workers = args.workers or min(len(jobs), mp.cpu_count())
	print(
		f'{config["name"]}: {len(entrants)} entrants, {len(matches)} matches x '
		f'{len(config["seeds"])} seeds = {len(jobs)} runs on {workers} worker(s)',
		file=sys.stderr,
	)

	board = None
	if args.gui:
		from ui.leaderboard import Leaderboard

		board = Leaderboard(
			title=config['name'], rank_by=args.rank_by, total=len(jobs), entrants=entrants
		)

	partial: list[dict] = []

	def apply_result(result: dict, n: int, total: int) -> None:
		partial.append(result)
		standing = rank(matches, partial, entrants, args.rank_by)
		seen = {row['code'] for row in standing['standings']}
		pending = [c for c in entrants if c not in seen]
		last = f'{matches[result["cell"]].roster_text}  seed {result["seed"]}'
		if board is not None:
			board.update(standing['standings'], n, pending, last_match=last)
		elif args.live:
			print_live_board(config['name'], matches, entrants, partial, args.rank_by, n, total)

	if board is not None:
		import pygame

		pace = 0.0 if pygame.display.get_driver() == 'dummy' else 0.12
		runs = execute_live(
			jobs,
			workers,
			worker=_run_match,
			on_progress=apply_result,
			idle=lambda: board.tick(),
			pace=pace,
		)
	else:
		runs = execute(
			jobs,
			workers,
			worker=_run_match,
			on_progress=apply_result if args.live else None,
		)

	report = {
		'tournament': config['name'],
		'description': config['description'],
		'config': config['source'],
		'entrants': entrants,
		'seeds': config['seeds'],
		'arenas': [a.label for a in config['arenas']],
		**rank(matches, runs, entrants, args.rank_by),
		'runs': runs,
	}
	written = write_outputs(report, args.out_dir)

	print_standings(report)
	print('\nwrote:')
	for path in written:
		print(f'  {path}')

	if board is not None:
		board.update(report['standings'], len(jobs), [])
		board.wait_to_close()


if __name__ == '__main__':
	main()
