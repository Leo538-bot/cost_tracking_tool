import uuid

import pytest

from app.splitting import (
    compute_balances,
    simplify_debts,
    split_by_weights,
    split_equally,
    validate_exact_split,
)


def ids(n: int) -> list[uuid.UUID]:
    return [uuid.UUID(int=i) for i in range(1, n + 1)]


class TestSplitEqually:
    def test_clean_division(self):
        a, b = ids(2)
        assert split_equally(1000, [a, b]) == {a: 500, b: 500}

    def test_remainder_is_never_lost(self):
        members = ids(3)
        result = split_equally(1000, members)
        assert sum(result.values()) == 1000
        assert sorted(result.values()) == [333, 333, 334]

    @pytest.mark.parametrize("total", [1, 7, 99, 100, 12345, 999999])
    @pytest.mark.parametrize("count", [1, 2, 3, 5, 7, 11])
    def test_shares_always_sum_to_total(self, total, count):
        assert sum(split_equally(total, ids(count)).values()) == total

    def test_single_cent_between_many(self):
        result = split_equally(1, ids(4))
        assert sum(result.values()) == 1
        assert sorted(result.values()) == [0, 0, 0, 1]

    def test_rejects_empty_member_list(self):
        with pytest.raises(ValueError):
            split_equally(100, [])


class TestSplitByWeights:
    def test_double_weight_pays_double(self):
        a, b = ids(2)
        assert split_by_weights(900, {a: 2, b: 1}) == {a: 600, b: 300}

    def test_uneven_weights_sum_to_total(self):
        a, b, c = ids(3)
        result = split_by_weights(1000, {a: 1, b: 1, c: 1})
        assert sum(result.values()) == 1000

    @pytest.mark.parametrize("total", [1, 55, 1000, 33333])
    def test_largest_remainder_keeps_the_total(self, total):
        a, b, c = ids(3)
        result = split_by_weights(total, {a: 3, b: 2, c: 1})
        assert sum(result.values()) == total

    def test_rejects_zero_total_weight(self):
        a = ids(1)[0]
        with pytest.raises(ValueError):
            split_by_weights(100, {a: 0})


class TestExactSplit:
    def test_accepts_matching_total(self):
        a, b = ids(2)
        validate_exact_split(1000, {a: 400, b: 600})

    def test_rejects_mismatch(self):
        a, b = ids(2)
        with pytest.raises(ValueError, match="add up"):
            validate_exact_split(1000, {a: 400, b: 500})


class TestBalances:
    def test_single_expense(self):
        a, b = ids(2)
        balances = compute_balances(
            expenses=[(a, 1000, {a: 500, b: 500})],
            settlements=[],
            member_ids=[a, b],
        )
        assert balances == {a: 500, b: -500}

    def test_settlement_clears_debt(self):
        a, b = ids(2)
        balances = compute_balances(
            expenses=[(a, 1000, {a: 500, b: 500})],
            settlements=[(b, a, 500)],
            member_ids=[a, b],
        )
        assert balances == {a: 0, b: 0}

    def test_balances_always_net_to_zero(self):
        a, b, c = ids(3)
        balances = compute_balances(
            expenses=[
                (a, 3000, {a: 1000, b: 1000, c: 1000}),
                (b, 1000, {a: 334, b: 333, c: 333}),
                (c, 777, {b: 389, c: 388}),
            ],
            settlements=[(c, a, 200)],
            member_ids=[a, b, c],
        )
        assert sum(balances.values()) == 0


class TestSimplifyDebts:
    def test_two_people(self):
        a, b = ids(2)
        transfers = simplify_debts({a: 500, b: -500})
        assert len(transfers) == 1
        assert transfers[0].from_member_id == b
        assert transfers[0].to_member_id == a
        assert transfers[0].amount_cents == 500

    def test_settled_group_needs_no_transfers(self):
        a, b = ids(2)
        assert simplify_debts({a: 0, b: 0}) == []

    def test_transfers_exactly_clear_all_balances(self):
        a, b, c, d = ids(4)
        balances = {a: 1500, b: -400, c: -1100, d: 0}
        transfers = simplify_debts(balances)

        net = dict(balances)
        for t in transfers:
            net[t.from_member_id] += t.amount_cents
            net[t.to_member_id] -= t.amount_cents
        assert all(v == 0 for v in net.values())

    def test_produces_at_most_n_minus_one_transfers(self):
        members = ids(5)
        balances = {members[0]: 1000, members[1]: 500}
        balances |= {m: -500 for m in members[2:]}
        assert len(simplify_debts(balances)) <= len(members) - 1
