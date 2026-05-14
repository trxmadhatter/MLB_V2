import pytest
from consensus import american_to_decimal, american_to_implied, vig_remove_pair, compute_consensus


class TestAmericanToDecimal:
    def test_positive_odds(self):
        assert american_to_decimal(100) == 2.0

    def test_positive_odds_plus150(self):
        assert american_to_decimal(150) == 2.5

    def test_negative_odds_minus110(self):
        assert abs(american_to_decimal(-110) - 1.9091) < 0.001

    def test_negative_odds_minus200(self):
        assert american_to_decimal(-200) == 1.5

    def test_even_odds(self):
        assert american_to_decimal(100) == 2.0


class TestAmericanToImplied:
    def test_even_money(self):
        assert american_to_implied(100) == 0.5

    def test_minus_110(self):
        assert abs(american_to_implied(-110) - 0.5238) < 0.001


class TestVigRemovePair:
    def test_symmetric_market(self):
        over, under = vig_remove_pair(-110, -110)
        assert abs(over - 0.5) < 0.001
        assert abs(under - 0.5) < 0.001
        assert abs(over + under - 1.0) < 1e-9

    def test_asymmetric_market(self):
        over, under = vig_remove_pair(-130, 110)
        assert over > under
        assert abs(over + under - 1.0) < 1e-9

    def test_sums_to_one(self):
        over, under = vig_remove_pair(-115, -105)
        assert abs(over + under - 1.0) < 1e-9


class TestComputeConsensus:
    def _rows(self, books: dict[str, tuple[int, int]]) -> list[dict]:
        rows = []
        for key, (op, up) in books.items():
            rows.append({"bookmaker_key": key, "selection": "Over",  "point": 7.5, "price": op})
            rows.append({"bookmaker_key": key, "selection": "Under", "point": 7.5, "price": up})
        return rows

    def test_returns_ok_with_three_books(self):
        rows = self._rows({
            "draftkings": (-115, -105),
            "fanduel":    (-112, -108),
            "betmgm":     (-110, -110),
        })
        result = compute_consensus(rows, min_books=3)
        assert result["ok"] is True
        assert result["book_count"] == 3
        assert abs(result["fair_prob_over"] + result["fair_prob_under"] - 1.0) < 1e-9

    def test_excludes_bovada_from_consensus(self):
        rows = self._rows({
            "bovada":     (-120, 100),
            "draftkings": (-115, -105),
            "fanduel":    (-112, -108),
            "betmgm":     (-110, -110),
        })
        result = compute_consensus(rows, min_books=3, bovada_keys={"bovada"})
        assert result["ok"] is True
        assert result["book_count"] == 3

    def test_insufficient_books_returns_false(self):
        rows = self._rows({
            "draftkings": (-115, -105),
            "fanduel":    (-112, -108),
        })
        result = compute_consensus(rows, min_books=3)
        assert result["ok"] is False
        assert result["reason"] == "insufficient_consensus_books"

    def test_book_missing_under_excluded(self):
        rows = [
            {"bookmaker_key": "draftkings", "selection": "Over",  "point": 7.5, "price": -115},
            {"bookmaker_key": "fanduel",    "selection": "Over",  "point": 7.5, "price": -112},
            {"bookmaker_key": "fanduel",    "selection": "Under", "point": 7.5, "price": -108},
            {"bookmaker_key": "betmgm",     "selection": "Over",  "point": 7.5, "price": -110},
            {"bookmaker_key": "betmgm",     "selection": "Under", "point": 7.5, "price": -110},
            {"bookmaker_key": "espnbet",    "selection": "Over",  "point": 7.5, "price": -113},
            {"bookmaker_key": "espnbet",    "selection": "Under", "point": 7.5, "price": -107},
        ]
        result = compute_consensus(rows, min_books=3)
        assert result["ok"] is True
        assert result["book_count"] == 3

    def test_fair_prob_symmetric_books(self):
        rows = self._rows({
            "draftkings": (-110, -110),
            "fanduel":    (-110, -110),
            "betmgm":     (-110, -110),
        })
        result = compute_consensus(rows, min_books=3)
        assert result["ok"] is True
        assert abs(result["fair_prob_over"] - 0.5) < 1e-6
