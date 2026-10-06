from models.cli import settings


def test_defaults():
	args = settings([])
	assert args.players == [('g', 10), ('r', 10)]
	assert args.rounds == 100
	assert args.bonus == 100.0
	assert args.dims == 5
	assert args.monotonic == 2
	assert args.distribution == 'mixed'
	assert args.dist_file is None
	assert args.seed == 4444
	assert args.timeout == 1.0
	assert args.log == ''
	assert not args.gui
	assert not args.summary_only


def test_player_flag_is_repeatable():
	args = settings(['--player', 'g', '4', '--player', '7', '2'])
	assert args.players == [('g', 4), ('7', 2)]


def test_short_flags():
	args = settings(['-t', '30', '-B', '250', '-d', '8', '-m', '3'])
	assert (args.rounds, args.bonus, args.dims, args.monotonic) == (30, 250.0, 8, 3)


def test_no_log_wins():
	assert settings(['--no-log']).log is None
	assert settings(['--log', 'x.log']).log == 'x.log'


def test_distribution_options():
	assert settings(['--dist', 'uniform']).distribution == 'uniform'
	assert settings(['--dist-file', 'p.json']).dist_file == 'p.json'
