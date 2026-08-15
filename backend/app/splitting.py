"""Money splitting and debt simplification.

Everything works in integer minor units (cents). The invariant that matters:
the shares of an expense always sum back to exactly the expense total.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


def split_equally(total_cents: int, member_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Split as evenly as integers allow, handing leftover cents to the first members.

    3 people splitting 10.00 EUR get 3.34 / 3.33 / 3.33 -- never 3.33 * 3 = 9.99.
    """
    if not member_ids:
        raise ValueError("cannot split between zero members")

    count = len(member_ids)
    base, remainder = divmod(abs(total_cents), count)
    sign = -1 if total_cents < 0 else 1

    return {
        member_id: sign * (base + (1 if index < remainder else 0))
        for index, member_id in enumerate(member_ids)
    }


def split_by_weights(total_cents: int, weights: dict[uuid.UUID, int]) -> dict[uuid.UUID, int]:
    """Split proportionally to integer weights (a couple sharing a room counts as 2).

    Largest-remainder method, so the parts still sum to the exact total.
    """
    if not weights:
        raise ValueError("cannot split between zero members")
    total_weight = sum(weights.values())
    if total_weight <= 0:
        raise ValueError("total weight must be positive")

    sign = -1 if total_cents < 0 else 1
    magnitude = abs(total_cents)

    exact = {mid: magnitude * w for mid, w in weights.items()}
    floors = {mid: value // total_weight for mid, value in exact.items()}
    assigned = sum(floors.values())
    leftover = magnitude - assigned

    # Hand the remaining cents to whoever was rounded down hardest.
    ranked = sorted(weights, key=lambda mid: (-(exact[mid] % total_weight), str(mid)))
    for mid in ranked[:leftover]:
        floors[mid] += 1

    return {mid: sign * value for mid, value in floors.items()}


def validate_exact_split(total_cents: int, amounts: dict[uuid.UUID, int]) -> None:
    if not amounts:
        raise ValueError("cannot split between zero members")
    given = sum(amounts.values())
    if given != total_cents:
        raise ValueError(
            f"shares add up to {given / 100:.2f} but the expense is {total_cents / 100:.2f}"
        )


@dataclass(frozen=True)
class Transfer:
    from_member_id: uuid.UUID
    to_member_id: uuid.UUID
    amount_cents: int


def compute_balances(
    *,
    expenses: list[tuple[uuid.UUID, int, dict[uuid.UUID, int]]],
    settlements: list[tuple[uuid.UUID, uuid.UUID, int]],
    member_ids: list[uuid.UUID],
) -> dict[uuid.UUID, int]:
    """Net position per member: positive = is owed money, negative = owes money.

    `expenses` is (payer_id, total_cents, {member_id: owed_cents}).
    `settlements` is (from_member_id, to_member_id, amount_cents) -- cash already handed over.
    """
    balances: dict[uuid.UUID, int] = dict.fromkeys(member_ids, 0)

    for payer_id, total_cents, shares in expenses:
        balances[payer_id] = balances.get(payer_id, 0) + total_cents
        for member_id, owed in shares.items():
            balances[member_id] = balances.get(member_id, 0) - owed

    # Paying someone back reduces what you owe and what they are owed.
    for from_id, to_id, amount in settlements:
        balances[from_id] = balances.get(from_id, 0) + amount
        balances[to_id] = balances.get(to_id, 0) - amount

    return balances


def simplify_debts(balances: dict[uuid.UUID, int]) -> list[Transfer]:
    """Turn net balances into a short list of "X pays Y" transfers.

    Greedy largest-debtor-to-largest-creditor matching. Not provably minimal in every
    edge case, but it produces at most n-1 transfers and is what people expect to see.
    """
    debtors = sorted(
        ((mid, -amount) for mid, amount in balances.items() if amount < 0),
        key=lambda pair: (-pair[1], str(pair[0])),
    )
    creditors = sorted(
        ((mid, amount) for mid, amount in balances.items() if amount > 0),
        key=lambda pair: (-pair[1], str(pair[0])),
    )

    transfers: list[Transfer] = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        debtor_id, owed = debtors[i]
        creditor_id, due = creditors[j]
        amount = min(owed, due)

        if amount > 0:
            transfers.append(
                Transfer(from_member_id=debtor_id, to_member_id=creditor_id, amount_cents=amount)
            )

        owed -= amount
        due -= amount
        debtors[i] = (debtor_id, owed)
        creditors[j] = (creditor_id, due)

        if owed == 0:
            i += 1
        if due == 0:
            j += 1

    return transfers
