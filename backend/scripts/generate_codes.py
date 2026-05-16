"""Generate one or more activation codes.

Usage::

    uv run python -m scripts.generate_codes --tier beta_30d --count 10
    uv run python -m scripts.generate_codes --tier beta_pro_30d --count 1 --note "stripe order 42"

The codes are committed to the database and printed to stdout (one per line)
so they can be pasted into a Payment Link follow-up email.
"""

from __future__ import annotations

import argparse
import asyncio

from app.db.database import async_session_factory
from app.services.activation import TIERS, create_codes


async def _run(tier: str, count: int, note: str | None) -> None:
    async with async_session_factory() as session:
        try:
            codes = await create_codes(
                session, tier=tier, count=count, note=note
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    for c in codes:
        print(c.code)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tier",
        required=True,
        choices=sorted(TIERS.keys()),
        help="Which tier of code to generate.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="How many codes to generate (default 1).",
    )
    parser.add_argument(
        "--note",
        default=None,
        help="Free-text note attached to each generated code (buyer / order id).",
    )
    args = parser.parse_args()
    if args.count < 1:
        parser.error("--count must be >= 1")
    asyncio.run(_run(args.tier, args.count, args.note))


if __name__ == "__main__":
    main()
