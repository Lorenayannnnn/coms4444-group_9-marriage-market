import argparse
from dataclasses import dataclass

from models.profile import PRESETS


@dataclass
class Settings:
	players: list[tuple[str, int]]
	rounds: int
	bonus: float
	dims: int
	monotonic: int
	distribution: str
	dist_file: str | None
	seed: int
	timeout: float
	summary_only: bool
	gui: bool
	log: str | None


def settings(argv: list[str] | None = None) -> Settings:
	parser = argparse.ArgumentParser(description='Run a marriage market simulation.')
	parser.add_argument(
		'--player',
		action='append',
		nargs=2,
		metavar=('CODE', 'COUNT'),
		help='Add COUNT people running player CODE (e.g. --player g 10). Repeatable. '
		'N is the total count and must be even.',
	)
	parser.add_argument('-t', '--rounds', type=int, default=100, help='Rounds of dating, t.')
	parser.add_argument('-B', '--bonus', type=float, default=100.0, help='Marriage bonus B.')
	parser.add_argument('-d', '--dims', type=int, default=5, help='Profile dimensions, d.')
	parser.add_argument(
		'-m',
		'--monotonic',
		type=int,
		default=2,
		help='How many of the first dimensions are monotonic, m <= d.',
	)
	parser.add_argument(
		'--dist',
		choices=PRESETS,
		default='mixed',
		dest='distribution',
		help='Preset distribution P for every dimension.',
	)
	parser.add_argument(
		'--dist-file',
		default=None,
		metavar='PATH',
		help='JSON file holding P as d rows of 11 probabilities. Overrides --dist.',
	)
	parser.add_argument('--seed', type=int, default=4444, help='Random seed.')
	parser.add_argument(
		'--timeout',
		type=float,
		default=1.0,
		help='Per-call wall-clock budget for player code, in seconds. 0 disables.',
	)
	parser.add_argument(
		'--summary-only',
		action='store_true',
		help="Discard each round's RoundRecord once it has been played. The results JSON is "
		'unchanged; a long run just stops holding one record per round in memory.',
	)
	parser.add_argument('--gui', action='store_true', help='Launch the visualizer.')
	parser.add_argument(
		'--log',
		default='',
		metavar='PATH',
		help='Write a per-round debug log (default: logs/marriage-*.log). Pass a path to '
		'choose the file. Sweeps do not write one.',
	)
	parser.add_argument(
		'--no-log',
		action='store_true',
		help='Do not write a debug log.',
	)

	args = parser.parse_args(argv)

	pairs: list[tuple[str, int]] = []
	for code, count in args.player or [('g', '10'), ('r', '10')]:
		pairs.append((code, int(count)))

	return Settings(
		players=pairs,
		rounds=args.rounds,
		bonus=args.bonus,
		dims=args.dims,
		monotonic=args.monotonic,
		distribution=args.distribution,
		dist_file=args.dist_file,
		seed=args.seed,
		timeout=args.timeout,
		summary_only=args.summary_only,
		gui=args.gui,
		log=None if args.no_log else args.log,
	)
