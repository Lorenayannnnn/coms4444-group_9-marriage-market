import json
import random

import pytest

from models.profile import (
	PRESETS,
	VALUES,
	build_distribution,
	decrement,
	happiness,
	load_distribution,
	normal_row,
	sample_profile,
	uniform_row,
	validate_distribution,
)


def test_monotonic_dimensions_only_penalise_a_shortfall():
	# Wanted 7 and got 9 on a monotonic dimension: more is fine.
	assert decrement((7,), (9,), monotonic=1) == 0
	assert decrement((7,), (7,), monotonic=1) == 0
	assert decrement((7,), (4,), monotonic=1) == 9


def test_other_dimensions_penalise_both_directions():
	assert decrement((7,), (9,), monotonic=0) == 4
	assert decrement((7,), (4,), monotonic=0) == 9


def test_only_the_first_m_dimensions_are_monotonic():
	desired = (5, 5, 5)
	partner = (8, 8, 8)
	assert decrement(desired, partner, monotonic=0) == 27
	assert decrement(desired, partner, monotonic=1) == 18
	assert decrement(desired, partner, monotonic=3) == 0


def test_happiness_subtracts_half_the_partners_decrement():
	# Mine: wanted (8, 5), partner is (6, 7) with m=1 -> 4 + 4 = 8.
	# Theirs: wanted (4, 2), I am (3, 3) -> 1 + 1 = 2, halved to 1.
	assert happiness(100, (3, 3), (8, 5), (6, 7), (4, 2), monotonic=1) == 100 - 8 - 1


def test_happiness_can_be_negative():
	assert happiness(0, (0,), (10,), (0,), (10,), monotonic=0) == -150


@pytest.mark.parametrize('name', PRESETS)
def test_presets_are_valid_distributions(name):
	table = build_distribution(name, dims=6, monotonic=2)
	assert validate_distribution(table, 6) == table


def test_mixed_uses_normal_rows_for_monotonic_dimensions():
	table = build_distribution('mixed', dims=4, monotonic=2)
	assert table[0] == normal_row(5.0, 2.0)
	assert table[1] == normal_row(5.0, 2.0)
	assert table[2] == uniform_row()


def test_unknown_preset_is_rejected():
	with pytest.raises(ValueError, match='unknown distribution'):
		build_distribution('bimodal', dims=2, monotonic=0)


def test_validate_rejects_rows_that_do_not_sum_to_one():
	with pytest.raises(ValueError, match='sums to'):
		validate_distribution([[0.5] * 11], 1)


def test_validate_rejects_wrong_shapes():
	with pytest.raises(ValueError, match='one row per dimension'):
		validate_distribution([uniform_row()], 2)
	with pytest.raises(ValueError, match='11 entries'):
		validate_distribution([[0.5, 0.5]], 1)


def test_validate_rejects_negative_probabilities():
	row = [0.0] * 11
	row[0], row[1], row[2] = 1.5, -1.0, 0.5
	with pytest.raises(ValueError, match='negative'):
		validate_distribution([row], 1)


def test_load_distribution_accepts_a_bare_list_or_a_P_key(tmp_path):
	rows = [list(uniform_row()), list(normal_row())]
	bare = tmp_path / 'bare.json'
	bare.write_text(json.dumps(rows))
	keyed = tmp_path / 'keyed.json'
	keyed.write_text(json.dumps({'P': rows}))
	assert load_distribution(bare, 2) == load_distribution(keyed, 2)


def test_samples_stay_on_the_scale_and_follow_the_distribution():
	only_seven = [0.0] * 11
	only_seven[7] = 1.0
	table = (uniform_row(), tuple(only_seven))
	rng = random.Random(1)
	for _ in range(200):
		profile = sample_profile(rng, table)
		assert len(profile) == 2
		assert profile[0] in VALUES
		assert profile[1] == 7
