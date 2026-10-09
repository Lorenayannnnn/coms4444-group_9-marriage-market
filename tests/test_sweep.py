import json
from pathlib import Path

import pytest

import sweep
from sweep import Cell, aggregate, build_jobs, execute, load_config, summarise

CONFIGS = sorted(p for p in Path('configs').glob('*.json') if p.stem != 'tournament')


@pytest.mark.parametrize('path', CONFIGS, ids=lambda p: p.stem)
def test_shipped_configs_load_and_validate(path):
	config = load_config(path)
	assert config.cells
	sweep.validate(config)


def test_grid_expands_as_a_cross_product(tmp_path):
	path = tmp_path / 'grid.json'
	path.write_text(
		json.dumps(
			{
				'defaults': {'players': [['g', 4]]},
				'grid': {'bonus': [50, 100], 'distribution': ['uniform', 'normal']},
				'cells': [{'label': 'extra', 'players': [['r', 2]]}],
			}
		)
	)
	config = load_config(path)
	labels = [c.label for c in config.cells]
	assert labels == [
		'bonus=50 distribution=uniform',
		'bonus=50 distribution=normal',
		'bonus=100 distribution=uniform',
		'bonus=100 distribution=normal',
		'extra',
	]
	assert config.cells[-1].people == 2


def test_validate_rejects_an_odd_market(tmp_path):
	path = tmp_path / 'odd.json'
	path.write_text(json.dumps({'cells': [{'players': [['g', 3]]}]}))
	with pytest.raises(SystemExit, match='N must be even'):
		sweep.validate(load_config(path))


def test_summarise_skips_missing_values():
	assert summarise([None, None])['mean'] is None
	stats = summarise([1.0, None, 3.0])
	assert stats['mean'] == 2.0
	assert stats['min'] == 1.0


def _tiny_config():
	cell = Cell(
		label='tiny',
		players=(('g', 4), ('r', 2)),
		rounds=15,
		bonus=100.0,
		dims=4,
		monotonic=1,
		distribution='mixed',
		timeout=0,
	)
	return sweep.SweepConfig(name='tiny', description='', seeds=[1, 2], cells=[cell])


def test_sweeps_are_deterministic():
	config = _tiny_config()
	first = aggregate(config, execute(build_jobs(config), workers=1, on_progress=lambda *a: None))
	again = aggregate(config, execute(build_jobs(config), workers=1, on_progress=lambda *a: None))
	assert json.dumps(first, sort_keys=True) == json.dumps(again, sort_keys=True)
	assert first['cells'][0]['seeds'] == [1, 2]


def test_main_writes_outputs(tmp_path, capsys):
	path = tmp_path / 'mini.json'
	path.write_text(
		json.dumps(
			{
				'name': 'mini',
				'defaults': {'players': [['g', 4]], 'rounds': 5, 'timeout': 0},
				'cells': [{'label': 'only'}],
				'seeds': [1],
			}
		)
	)
	sweep.main([str(path), '--out-dir', str(tmp_path / 'out'), '--workers', '1'])
	assert (tmp_path / 'out' / 'mini.json').exists()
	assert (tmp_path / 'out' / 'mini.csv').exists()
	assert (tmp_path / 'out' / 'mini_runs.csv').exists()
	assert 'only' in capsys.readouterr().out


def test_list_limit_configuration_reaches_sweep_jobs(tmp_path):
	path = tmp_path / 'limits.json'
	path.write_text(
		json.dumps(
			{
				'defaults': {'players': [['g', 100]], 'rounds': 1},
				'grid': {'list_multiple': [0, 2, 4]},
			}
		)
	)
	config = load_config(path)
	assert [cell.list_multiple for cell in config.cells] == [0, 2, 4]
	assert [job['list_multiple'] for job in build_jobs(config)] == [0, 2, 4]
	sweep.validate(config)
