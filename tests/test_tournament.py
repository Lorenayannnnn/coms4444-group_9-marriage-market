import json

import tournament
from tournament import Arena, build_matches, load_config, rank


def _arena(people: int = 6) -> Arena:
	return Arena(
		people=people,
		rounds=10,
		bonus=100.0,
		dims=4,
		monotonic=1,
		distribution='mixed',
		timeout=0,
	)


def _config(kinds=('solo', 'pairs', 'mix'), people: int = 6) -> dict:
	return {'arenas': [_arena(people)], 'rosters': list(kinds)}


def test_shipped_config_loads():
	config = load_config('configs/tournament.json')
	assert [a.bonus for a in config['arenas']] == [50.0, 100.0, 200.0]
	assert config['rosters'] == ['solo', 'pairs', 'mix']


def test_roster_kinds():
	matches, skipped = build_matches(_config(), ['a', 'b', 'c'])
	assert not skipped
	by_kind: dict[str, list] = {}
	for m in matches:
		by_kind.setdefault(m.kind, []).append(m.roster)
	assert by_kind['solo'] == [('a',) * 6, ('b',) * 6, ('c',) * 6]
	assert by_kind['pairs'] == [
		('a', 'a', 'a', 'b', 'b', 'b'),
		('a', 'a', 'a', 'c', 'c', 'c'),
		('b', 'b', 'b', 'c', 'c', 'c'),
	]
	assert by_kind['mix'] == [('a', 'b', 'c', 'a', 'b', 'c')]


def test_mix_needs_three_groups():
	matches, _ = build_matches(_config(), ['a', 'b'])
	assert {m.kind for m in matches} == {'solo', 'pairs'}


def test_odd_markets_are_skipped():
	matches, skipped = build_matches(_config(people=5), ['a', 'b'])
	assert not matches
	assert 'N must be even' in skipped[0]


def test_rank_sorts_highest_first_and_counts_seats():
	matches, _ = build_matches(_config(kinds=('pairs',), people=4), ['g', 'r'])
	runs = [
		{
			'cell': 0,
			'seed': 1,
			'roster': ['g', 'g', 'r', 'r'],
			'faults': 0,
			'seats': [
				{'code': 'g', 'happiness': 50.0, 'positive': True, 'married': True},
				{'code': 'g', 'happiness': 30.0, 'positive': True, 'married': True},
				{'code': 'r', 'happiness': -10.0, 'positive': False, 'married': True},
				{'code': 'r', 'happiness': 0.0, 'positive': False, 'married': False},
			],
		}
	]
	report = rank(matches, runs, ['g', 'r'], 'positive_rate')
	standings = report['standings']
	assert [row['code'] for row in standings] == ['g', 'r']
	assert standings[0]['positive_rate']['mean'] == 1.0
	assert standings[1]['mean_happiness']['mean'] == -5.0
	assert standings[1]['married_rate']['mean'] == 0.5
	assert standings[0]['seats'] == 2


def test_main_runs_end_to_end(tmp_path, capsys):
	path = tmp_path / 't.json'
	path.write_text(
		json.dumps(
			{
				'name': 'mini',
				'seeds': [1],
				'defaults': {'people': 6, 'rounds': 8, 'timeout': 0},
			}
		)
	)
	tournament.main([str(path), '--out-dir', str(tmp_path / 'out'), '--workers', '1'])
	report = json.loads((tmp_path / 'out' / 'mini.json').read_text())
	assert {row['code'] for row in report['standings']} == {'g', 'r'}
	assert (tmp_path / 'out' / 'mini_standings.csv').exists()
	assert (tmp_path / 'out' / 'mini_runs.csv').exists()
	assert 'ranked by positive_rate' in capsys.readouterr().out
