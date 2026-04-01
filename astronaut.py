#!/usr/bin/env python3
"""
Astronaut mission control.

This file is a self-contained extraction and adaptation of the matrix-driven
"mode 2" programming engine in C.py, rebuilt as a safer and self-managed
Python simulation game called Astronaut.

Key design choices:
- preserves the original matrix / cursor / command-pointer shape from C.py
- removes raw exec-based command execution and replaces it with a safe registry
- ports the Infinity / n-dimensional fabric logic into Python for config,
  witness, matching, and matrix derivation
- bootstraps its own runtime files, matrix, and mission state on first run
- uses a 29x29 (= 841) matrix preset derived from an exact n=2 match, with
  7-symbol ternary cell addresses inspired by the attached 012 generator

The script runs in headless mode by default and can optionally open a pygame
window if pygame is installed and a display is available.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import shlex
import sys
import textwrap
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

try:
    import pygame  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    pygame = None


BOOTSTRAP_UNIQUE = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
BOOTSTRAP_PAYLOAD = (BOOTSTRAP_UNIQUE * 14)[:841]
DEFAULT_RUNTIME_DIR = Path("astronaut_runtime")
DEFAULT_CONFIG = {
    "primary_alphabet": 7,
    "secondary_alphabet": 10,
    "secondary_length": 5,
    "dimension": 2,
    "min_root": 2,
    "range_s_min": 1,
    "range_s_max": 12,
    "match_limit": 12,
    "match_primary_min": 2,
    "match_primary_max": 128,
    "match_h_radius": 0,
}


class MathUtil:
    @staticmethod
    def bounded_pow(base: int, exp: int, limit: int) -> int:
        result = 1
        for _ in range(exp):
            if base != 0 and result > limit // max(1, base):
                return limit + 1
            result *= base
            if result > limit:
                return limit + 1
        return result

    @staticmethod
    def exact_nth_root(x: int, n: int) -> Optional[int]:
        if n <= 0 or x < 0:
            raise ValueError("Invalid nth-root arguments.")
        if x in (0, 1):
            return x
        lo, hi = 1, x
        while lo <= hi:
            mid = (lo + hi) // 2
            power = MathUtil.bounded_pow(mid, n, x)
            if power == x:
                return mid
            if power < x:
                lo = mid + 1
            else:
                hi = mid - 1
        return None

    @staticmethod
    def nth_root_floor(x: int, n: int) -> int:
        if n <= 0 or x < 0:
            raise ValueError("Invalid nth-root arguments.")
        if x in (0, 1):
            return x
        lo, hi = 1, x
        best = 1
        while lo <= hi:
            mid = (lo + hi) // 2
            power = MathUtil.bounded_pow(mid, n, x)
            if power == x:
                return mid
            if power < x:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        return best

    @staticmethod
    def valid_length_info(length: int, dimension: int, min_root: int) -> dict[str, Any]:
        root = MathUtil.exact_nth_root(length, dimension)
        return {"valid": root is not None and root >= min_root, "m": root}

    @staticmethod
    def nearest_valid_length(target: int, dimension: int, min_root: int, lmax: int) -> dict[str, Any]:
        if target < 1 or lmax < 1:
            return {
                "closest_L": None,
                "m": None,
                "gap": None,
                "exact": False,
                "below_L": None,
                "above_L": None,
            }

        exact = MathUtil.valid_length_info(target, dimension, min_root)
        if exact["valid"] and target <= lmax:
            return {
                "closest_L": target,
                "m": exact["m"],
                "gap": 0,
                "exact": True,
                "below_L": target,
                "above_L": target,
            }

        root_floor = MathUtil.nth_root_floor(target, dimension)
        candidates: dict[int, int] = {}
        start = max(min_root, root_floor - 3)
        end = root_floor + 4
        for m in range(start, end + 1):
            length = MathUtil.bounded_pow(m, dimension, sys.maxsize >> 4)
            if 1 <= length <= lmax:
                candidates[length] = m

        if not candidates:
            max_root = MathUtil.nth_root_floor(lmax, dimension)
            if max_root >= min_root:
                length = MathUtil.bounded_pow(max_root, dimension, sys.maxsize >> 4)
                return {
                    "closest_L": length,
                    "m": max_root,
                    "gap": abs(length - target),
                    "exact": False,
                    "below_L": length,
                    "above_L": None,
                }
            return {
                "closest_L": None,
                "m": None,
                "gap": None,
                "exact": False,
                "below_L": None,
                "above_L": None,
            }

        best_l = None
        best_m = None
        best_gap = None
        below = None
        above = None
        for length in sorted(candidates):
            if length <= target:
                below = length
            if length >= target and above is None:
                above = length
            gap = abs(length - target)
            if best_gap is None or gap < best_gap or (gap == best_gap and (best_l is None or length > best_l)):
                best_gap = gap
                best_l = length
                best_m = candidates[length]

        return {
            "closest_L": best_l,
            "m": best_m,
            "gap": best_gap,
            "exact": False,
            "below_L": below,
            "above_L": above,
        }

    @staticmethod
    def classify_base(base: int) -> str:
        if base < 2:
            return "invalid"
        if base == 2:
            return "prime"
        if base % 2 == 0:
            return "other"
        root = int(math.isqrt(base))
        for candidate in range(3, root + 1, 2):
            if base % candidate == 0:
                return "other"
        return "prime"

    @staticmethod
    def centered_integers(center: int, minimum: int, maximum: int, limit: int) -> list[int]:
        result: list[int] = []
        seen: set[int] = set()

        def push(value: int) -> None:
            if value < minimum or value > maximum or value in seen or len(result) >= limit:
                return
            seen.add(value)
            result.append(value)

        push(center)
        distance = 1
        while len(result) < limit and (center - distance >= minimum or center + distance <= maximum):
            push(center - distance)
            push(center + distance)
            distance += 1
        return result


class Fabric:
    @staticmethod
    def max_primary_length(h: int, s: int, p: int) -> int:
        if h < 2 or s < 1 or p < 2:
            raise ValueError("Require h >= 2, s >= 1, p >= 2.")
        target = pow(h, s)
        lo, hi = 1, 1
        while pow(p, hi) < target:
            hi *= 2
        while lo < hi:
            mid = (lo + hi) // 2
            if pow(p, mid) >= target:
                hi = mid
            else:
                lo = mid + 1
        return lo

    @staticmethod
    def valid_lengths_up_to(lmax: int, dimension: int, min_root: int) -> list[dict[str, int]]:
        result: list[dict[str, int]] = []
        for length in range(1, lmax + 1):
            info = MathUtil.valid_length_info(length, dimension, min_root)
            if info["valid"]:
                result.append({"L": length, "m": int(info["m"])})
        return result

    @staticmethod
    def min_secondary_length_for_primary_length(h: int, p: int, length: int) -> int:
        if length < 1:
            raise ValueError("L must be >= 1.")
        threshold = pow(p, length - 1)
        s = 1
        while pow(h, s) <= threshold:
            s += 1
        return s


class TextAnalyzer:
    @staticmethod
    def analyze(text: str) -> dict[str, Any]:
        chars = list(text)
        unique_chars = sorted(set(chars))
        line_count = 0 if text == "" else text.count("\n") + 1
        return {
            "chars": chars,
            "char_length": len(chars),
            "unique_count": len(unique_chars),
            "unique_chars": unique_chars,
            "line_count": line_count,
            "preview": TextAnalyzer.preview_unique_chars(unique_chars),
        }

    @staticmethod
    def escape_char(ch: str) -> str:
        if ch == "\n":
            return "\\n"
        if ch == "\r":
            return "\\r"
        if ch == "\t":
            return "\\t"
        if ch == " ":
            return "<space>"
        return ch

    @staticmethod
    def preview_unique_chars(chars: Iterable[str]) -> str:
        preview = []
        for ch in chars:
            preview.append(TextAnalyzer.escape_char(ch))
            if len(preview) >= 80:
                break
        return " ".join(preview)


class MatchEngine:
    @staticmethod
    def rank(cfg: dict[str, Any], analysis: dict[str, int], limit: int) -> list[dict[str, Any]]:
        limit = max(1, min(12, limit))
        target_length = max(1, int(analysis["char_length"]))
        observed_unique = max(1, int(analysis["unique_count"]))
        dimension = int(cfg["dimension"])
        min_root = int(cfg["min_root"])
        primary_min = max(2, int(cfg["match_primary_min"]))
        primary_max = max(primary_min, int(cfg["match_primary_max"]))
        h_radius = max(0, int(cfg["match_h_radius"]))

        p_candidates = MathUtil.centered_integers(observed_unique, primary_min, primary_max, max(24, limit * 4))
        h_candidates = MathUtil.centered_integers(
            observed_unique,
            max(2, observed_unique - h_radius),
            max(2, observed_unique + h_radius),
            max(1, 2 * h_radius + 1),
        )
        if not h_candidates:
            h_candidates = [max(2, observed_unique)]
        return MatchEngine.rank_with_candidates(cfg, analysis, limit, p_candidates, h_candidates, dimension)

    @staticmethod
    def rank_with_candidates(
        cfg: dict[str, Any],
        analysis: dict[str, int],
        limit: int,
        p_candidates: list[int],
        h_candidates: list[int],
        dimension: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(12, limit))
        target_length = max(1, int(analysis["char_length"]))
        observed_unique = max(1, int(analysis["unique_count"]))
        min_root = int(cfg["min_root"])
        dimension = max(1, int(cfg["dimension"] if dimension is None else dimension))
        p_candidates = MatchEngine._sanitize_candidates(p_candidates, 2)
        h_candidates = MatchEngine._sanitize_candidates(h_candidates, 2)
        if not p_candidates or not h_candidates:
            return []

        rows: list[dict[str, Any]] = []
        for h in h_candidates:
            for p in p_candidates:
                s = target_length
                lmax = Fabric.max_primary_length(h, s, p)
                nearest = MathUtil.nearest_valid_length(target_length, dimension, min_root, lmax)
                if nearest["closest_L"] is None:
                    continue
                gap = int(nearest["gap"])
                closest_l = int(nearest["closest_L"])
                root = int(nearest["m"])
                exact = bool(nearest["exact"])
                h_delta = abs(h - observed_unique)
                p_delta = abs(p - observed_unique)
                score = (-1000000 if exact else 0) + gap * 1000 + h_delta * 100 + p_delta
                rows.append(
                    {
                        "score": score,
                        "p": p,
                        "h": h,
                        "s": s,
                        "n": dimension,
                        "Lmax": lmax,
                        "closest_L": closest_l,
                        "m": root,
                        "gap": gap,
                        "exact": exact,
                        "base_type": MathUtil.classify_base(p),
                    }
                )

        rows.sort(key=lambda row: (row["score"], row["gap"], row["h"], row["p"]))
        unique_rows: list[dict[str, Any]] = []
        seen: set[tuple[int, int, int, int]] = set()
        for row in rows:
            key = (row["p"], row["h"], row["s"], row["n"])
            if key in seen:
                continue
            seen.add(key)
            unique_rows.append(row)
            if len(unique_rows) >= limit:
                break
        return unique_rows

    @staticmethod
    def _sanitize_candidates(candidates: Iterable[int], minimum: int) -> list[int]:
        result: list[int] = []
        seen: set[int] = set()
        for value in candidates:
            value = int(value)
            if value < minimum or value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result


class InfinitySession:
    def __init__(self) -> None:
        self.cfg = dict(DEFAULT_CONFIG)
        self.last: dict[str, Any] = {}
        self.last_matches: list[dict[str, Any]] = []
        self.last_paste_analysis: Optional[dict[str, Any]] = None

    def validate_config(self) -> None:
        int_keys = [
            "primary_alphabet",
            "secondary_alphabet",
            "secondary_length",
            "dimension",
            "min_root",
            "range_s_min",
            "range_s_max",
            "match_limit",
            "match_primary_min",
            "match_primary_max",
            "match_h_radius",
        ]
        for key in int_keys:
            self.cfg[key] = int(self.cfg[key])
        if self.cfg["primary_alphabet"] < 2 or self.cfg["secondary_alphabet"] < 2:
            raise ValueError("Alphabet lengths must be >= 2.")
        if self.cfg["secondary_length"] < 1 or self.cfg["dimension"] < 1 or self.cfg["min_root"] < 1:
            raise ValueError("secondary_length, dimension, and min_root must be >= 1.")
        if self.cfg["range_s_min"] < 1 or self.cfg["range_s_max"] < 1:
            raise ValueError("Traversal bounds must be >= 1.")
        if not (1 <= self.cfg["match_limit"] <= 12):
            raise ValueError("match_limit must be between 1 and 12.")
        if self.cfg["match_primary_min"] < 2 or self.cfg["match_primary_max"] < self.cfg["match_primary_min"]:
            raise ValueError("Invalid match_primary_min/max bounds.")
        if self.cfg["match_h_radius"] < 0:
            raise ValueError("match_h_radius must be >= 0.")

    def compact_analysis(self, analysis: dict[str, Any]) -> dict[str, Any]:
        return {
            "line_count": int(analysis["line_count"]),
            "char_length": int(analysis["char_length"]),
            "unique_count": int(analysis["unique_count"]),
            "unique_chars": list(analysis["unique_chars"]),
            "preview": str(analysis["preview"]),
        }

    def help_text(self) -> str:
        return textwrap.dedent(
            """
            Core:
              help | commands
              explain <topic>
              show
              set <key> <value>
              reset
              quit | exit

            Analysis:
              classify
              lengths [s]
              fabric traverse
              witness <L>

            Matching:
              paste [limit]
              match apply <rank>
              match refine <rank>

            Persistence / Export:
              save [file.json]
              load [file.json]
              export [file.json]

            Mission control:
              mission status
              mission matrix [radius]
              mission select <cell_id>
              mission goto <row> <col>
              mission execute [cell_id]
              mission step [ticks]
              mission reset
              mission launch
            """
        ).strip()

    def explain(self, topic: str) -> str:
        aliases = {"commands": "help", "fabric": "fabric traverse", "exit": "quit"}
        topic = aliases.get(topic.strip().lower(), topic.strip().lower())
        catalog = {
            "help": {
                "usage": "help | commands",
                "summary": "Show the grouped command list.",
                "mutates": False,
                "related": "explain <topic>, show",
            },
            "show": {
                "usage": "show",
                "summary": "Display the current configuration and derived state.",
                "mutates": False,
                "related": "lengths, fabric traverse",
            },
            "set": {
                "usage": "set <key> <value>",
                "summary": "Update one configuration key.",
                "mutates": True,
                "related": "show, reset",
            },
            "reset": {
                "usage": "reset",
                "summary": "Restore the default configuration.",
                "mutates": True,
                "related": "show, set",
            },
            "classify": {
                "usage": "classify",
                "summary": "Classify the current primary alphabet base.",
                "mutates": False,
                "related": "show, lengths",
            },
            "lengths": {
                "usage": "lengths [s]",
                "summary": "Compute valid primary lengths for one secondary length.",
                "mutates": False,
                "related": "show, fabric traverse, witness",
            },
            "fabric traverse": {
                "usage": "fabric traverse",
                "summary": "Sweep the configured s-range and visualize fabric growth.",
                "mutates": False,
                "related": "lengths, witness, export",
            },
            "witness": {
                "usage": "witness <L>",
                "summary": "Find the minimal s that realizes a target primary length.",
                "mutates": False,
                "related": "lengths, fabric traverse",
            },
            "paste": {
                "usage": "paste [limit]",
                "summary": "Analyze text and rank matching configs.",
                "mutates": True,
                "related": "match apply, match refine, export",
            },
            "match": {
                "usage": "match apply <rank> | match refine <rank>",
                "summary": "Operate on the cached ranked match list.",
                "mutates": True,
                "related": "paste, match apply, match refine",
            },
            "match apply": {
                "usage": "match apply <rank>",
                "summary": "Apply a ranked match to the active session config.",
                "mutates": True,
                "related": "paste, match refine, show",
            },
            "match refine": {
                "usage": "match refine <rank>",
                "summary": "Locally rerank around one cached match.",
                "mutates": True,
                "related": "paste, match apply, export",
            },
            "save": {
                "usage": "save [file.json]",
                "summary": "Persist the current configuration to JSON.",
                "mutates": False,
                "related": "load, show",
            },
            "load": {
                "usage": "load [file.json]",
                "summary": "Load configuration from JSON.",
                "mutates": True,
                "related": "save, show",
            },
            "export": {
                "usage": "export [file.json]",
                "summary": "Write the current cached payload as JSON.",
                "mutates": False,
                "related": "paste, fabric traverse, save",
            },
            "quit": {
                "usage": "quit | exit",
                "summary": "Exit the session.",
                "mutates": False,
                "related": "help",
            },
        }
        item = catalog.get(topic)
        if item is None:
            return "Unknown explain topic. Type 'help' or 'commands'."
        return (
            f"topic: {topic}\n"
            f"usage: {item['usage']}\n"
            f"summary: {item['summary']}\n"
            f"mutates session: {'true' if item['mutates'] else 'false'}\n"
            f"active config inputs: {', '.join(self.cfg.keys())}\n"
            f"constraints: h^s > p^(L-1); L is valid iff L = m^n and m >= min_root\n"
            f"related: {item['related']}"
        )

    def show(self) -> str:
        p = int(self.cfg["primary_alphabet"])
        h = int(self.cfg["secondary_alphabet"])
        s = int(self.cfg["secondary_length"])
        n = int(self.cfg["dimension"])
        min_root = int(self.cfg["min_root"])
        lmax = Fabric.max_primary_length(h, s, p)
        valid = Fabric.valid_lengths_up_to(lmax, n, min_root)
        lines = ["-" * 72]
        for key, value in self.cfg.items():
            lines.append(f"{key:22} : {value}")
        lines.extend(
            [
                "-" * 72,
                f"base classification     : {MathUtil.classify_base(p)}",
                f"max primary length      : {lmax}",
                f"valid lengths @ s={s:<4}   : {self.format_valid_list(valid)}",
                "fabric rule             : L is valid iff L = m^n and m >= min_root",
                "-" * 72,
            ]
        )
        return "\n".join(lines)

    def set_value(self, key: str, raw: str) -> str:
        if key not in self.cfg:
            raise ValueError(f"Unknown key: {key}")
        self.cfg[key] = int(raw)
        self.validate_config()
        return f"Updated {key}."

    def reset(self) -> str:
        self.cfg = dict(DEFAULT_CONFIG)
        self.last = {}
        self.last_matches = []
        self.last_paste_analysis = None
        return "Configuration reset."

    def classify(self) -> str:
        p = int(self.cfg["primary_alphabet"])
        return f"primary_alphabet={p} is {MathUtil.classify_base(p)}"

    def lengths(self, secondary_length: Optional[int] = None) -> str:
        s = max(1, int(self.cfg["secondary_length"] if secondary_length is None else secondary_length))
        h = int(self.cfg["secondary_alphabet"])
        p = int(self.cfg["primary_alphabet"])
        n = int(self.cfg["dimension"])
        min_root = int(self.cfg["min_root"])
        lmax = Fabric.max_primary_length(h, s, p)
        valid = Fabric.valid_lengths_up_to(lmax, n, min_root)
        self.last = {
            "type": "lengths",
            "secondary_length": s,
            "Lmax": lmax,
            "valid": valid,
            "config": dict(self.cfg),
        }
        return "\n".join(
            [
                f"secondary length s      : {s}",
                f"max primary length      : {lmax}",
                f"valid primary lengths   : {self.format_valid_list(valid)}",
            ]
        )

    def fabric_traverse(self) -> str:
        h = int(self.cfg["secondary_alphabet"])
        p = int(self.cfg["primary_alphabet"])
        n = int(self.cfg["dimension"])
        min_root = int(self.cfg["min_root"])
        s_min = int(self.cfg["range_s_min"])
        s_max = int(self.cfg["range_s_max"])
        if s_min > s_max:
            raise ValueError("range_s_min must be <= range_s_max.")
        rows: list[dict[str, Any]] = []
        out = [f"{'s':<8}{'Lmax':<10}{'count':<8}{'density':<10}valid primary lengths", "-" * 72]
        for s in range(s_min, s_max + 1):
            lmax = Fabric.max_primary_length(h, s, p)
            valid = Fabric.valid_lengths_up_to(lmax, n, min_root)
            valid_count = len(valid)
            density = (valid_count / lmax) if lmax > 0 else 0.0
            out.append(f"{s:<8}{lmax:<10}{valid_count:<8}{self.format_percent(density):<10}{self.format_valid_list(valid)}")
            rows.append({"s": s, "Lmax": lmax, "valid": valid, "valid_count": valid_count, "density": density})
        summary = self.summarize_fabric_rows(rows)
        out.extend(self.render_fabric_charts(rows, summary))
        self.last = {"type": "fabric_traverse", "rows": rows, "summary": summary, "config": dict(self.cfg)}
        return "\n".join(out)

    def witness(self, length: int) -> str:
        length = max(1, int(length))
        h = int(self.cfg["secondary_alphabet"])
        p = int(self.cfg["primary_alphabet"])
        n = int(self.cfg["dimension"])
        min_root = int(self.cfg["min_root"])
        valid = MathUtil.valid_length_info(length, n, min_root)
        s = Fabric.min_secondary_length_for_primary_length(h, p, length)
        self.last = {
            "type": "witness",
            "L": length,
            "valid": valid,
            "minimal_secondary_length": s,
            "config": dict(self.cfg),
        }
        return "\n".join(
            [
                f"target primary length   : {length}",
                f"dimension-valid         : {'true' if valid['valid'] else 'false'}",
                f"root m                  : {valid['m'] if valid['m'] is not None else 'n/a'}",
                f"minimal secondary s     : {s}",
                "condition               : h^s > p^(L-1)",
            ]
        )

    def paste_text(self, text: str, limit: Optional[int] = None) -> str:
        limit = int(self.cfg["match_limit"] if limit is None else limit)
        limit = max(1, min(12, limit))
        analysis = self.compact_analysis(TextAnalyzer.analyze(text))
        matches = MatchEngine.rank(self.cfg, analysis, limit)
        self.last_paste_analysis = analysis
        self.last_matches = matches
        self.last = {"type": "paste_match", "analysis": analysis, "matches": matches, "config": dict(self.cfg)}
        return self.render_match_results(analysis, matches)

    def match_apply(self, rank: int) -> str:
        row = self.require_match_row(rank)
        self.cfg["primary_alphabet"] = int(row["p"])
        self.cfg["secondary_alphabet"] = int(row["h"])
        self.cfg["secondary_length"] = int(row["s"])
        self.cfg["dimension"] = int(row["n"])
        self.validate_config()
        return f"Applied match #{rank} -> p={row['p']}, h={row['h']}, s={row['s']}, n={row['n']}"

    def match_refine(self, rank: int) -> str:
        if self.last_paste_analysis is None:
            raise RuntimeError("No paste analysis available yet. Run paste first.")
        row = self.require_match_row(rank)
        primary_min = max(2, int(self.cfg["match_primary_min"]))
        primary_max = max(primary_min, int(self.cfg["match_primary_max"]))
        p_candidates = MathUtil.centered_integers(int(row["p"]), primary_min, primary_max, 7)
        radius = max(1, int(self.cfg["match_h_radius"]))
        h_center = max(2, int(row["h"]))
        h_candidates = MathUtil.centered_integers(h_center, max(2, h_center - radius), max(2, h_center + radius), max(3, 2 * radius + 1))
        matches = MatchEngine.rank_with_candidates(
            self.cfg,
            self.last_paste_analysis,
            int(self.cfg["match_limit"]),
            p_candidates,
            h_candidates,
            int(row["n"]),
        )
        if not matches:
            raise RuntimeError("No refined matches found in the local search window.")
        self.last_matches = matches
        self.last = {
            "type": "match_refine",
            "source_rank": rank,
            "source_row": row,
            "analysis": self.last_paste_analysis,
            "candidate_window": {"p": p_candidates, "h": h_candidates},
            "matches": matches,
            "config": dict(self.cfg),
        }
        context = [
            "Refined match candidates (local rerank)",
            f"refinement source      : rank #{rank} -> p={row['p']}, h={row['h']}, s={row['s']}, n={row['n']}",
            f"candidate window       : p={', '.join(map(str, p_candidates))} | h={', '.join(map(str, h_candidates))}",
        ]
        return self.render_match_results(self.last_paste_analysis, matches, context, int(row["n"]))

    def save_config(self, path: Path) -> str:
        path.write_text(json.dumps(self.cfg, indent=2), encoding="utf-8")
        return f"Saved config to {path}"

    def load_config(self, path: Path) -> str:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for key in DEFAULT_CONFIG:
            if key in payload:
                self.cfg[key] = int(payload[key])
        self.validate_config()
        return f"Loaded config from {path}"

    def export_payload(self, path: Optional[Path] = None) -> str:
        payload = self.last or {"type": None, "config": dict(self.cfg)}
        rendered = json.dumps(payload, indent=2)
        if path is not None:
            path.write_text(rendered, encoding="utf-8")
            return f"Exported current payload to {path}"
        return rendered

    def require_match_row(self, rank: int) -> dict[str, Any]:
        if not self.last_matches:
            raise RuntimeError("No ranked matches available yet. Run paste first.")
        if rank < 1 or rank > len(self.last_matches):
            raise ValueError("Rank out of range.")
        return self.last_matches[rank - 1]

    @staticmethod
    def format_valid_list(valid: list[dict[str, int]]) -> str:
        if not valid:
            return "(none)"
        parts = []
        for row in valid:
            parts.append(f"{row['L']}(m={row['m']})")
            if len(parts) >= 18:
                parts.append("...")
                break
        return ", ".join(parts)

    @staticmethod
    def format_percent(value: float) -> str:
        return f"{value * 100:.2f}%"

    @staticmethod
    def summarize_fabric_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {
                "start_s": None,
                "end_s": None,
                "max_Lmax": 0,
                "max_Lmax_s": None,
                "best_density": 0.0,
                "best_density_s": None,
                "max_valid_count": 0,
                "max_valid_count_s": None,
            }
        max_lmax_row = max(rows, key=lambda row: row["Lmax"])
        best_density_row = max(rows, key=lambda row: row["density"])
        max_valid_row = max(rows, key=lambda row: row["valid_count"])
        return {
            "start_s": rows[0]["s"],
            "end_s": rows[-1]["s"],
            "max_Lmax": max_lmax_row["Lmax"],
            "max_Lmax_s": max_lmax_row["s"],
            "best_density": best_density_row["density"],
            "best_density_s": best_density_row["s"],
            "max_valid_count": max_valid_row["valid_count"],
            "max_valid_count_s": max_valid_row["s"],
        }

    def render_fabric_charts(self, rows: list[dict[str, Any]], summary: dict[str, Any]) -> list[str]:
        lines = [
            "-" * 72,
            (
                f"range summary          : s={summary['start_s']}..{summary['end_s']}"
                f" | max Lmax={summary['max_Lmax']} @ s={summary['max_Lmax_s']}"
                f" | best density={self.format_percent(float(summary['best_density']))} @ s={summary['best_density_s']}"
            ),
            f"max valid-count        : {summary['max_valid_count']} @ s={summary['max_valid_count_s']}",
            "-" * 72,
            "Lmax growth chart",
            "-----------------",
        ]
        bar_width = 32
        scale_max = max(1, int(summary["max_Lmax"]))
        for row in rows:
            filled = round((int(row["Lmax"]) / scale_max) * bar_width)
            lines.append(f"s={row['s']:<3} [{'#' * filled}{'.' * (bar_width - filled)}] {row['Lmax']}")
        lines.extend(["-" * 72, "Valid-density chart", "------------------"])
        for row in rows:
            filled = round(float(row["density"]) * bar_width)
            lines.append(f"s={row['s']:<3} [{'#' * filled}{'.' * (bar_width - filled)}] {self.format_percent(float(row['density']))}")
        return lines

    def render_match_results(
        self,
        analysis: dict[str, Any],
        matches: list[dict[str, Any]],
        context_lines: Optional[list[str]] = None,
        dimension: Optional[int] = None,
    ) -> str:
        lines = list(context_lines or [])
        lines.extend(
            [
                f"pasted text lines      : {analysis['line_count']}",
                f"pasted char length     : {analysis['char_length']}",
                f"observed unique chars  : {analysis['unique_count']}",
                f"effective sec alphabet : {max(2, int(analysis['unique_count']))}",
                f"active dimension       : {dimension if dimension is not None else int(self.cfg['dimension'])}",
                f"unique char preview    : {analysis['preview']}",
                "-" * 72,
                f"{'#':<4}{'p':<8}{'h':<8}{'s':<12}{'n':<6}{'Lmax':<10}{'closest_L':<12}{'m':<8}{'gap':<8}{'exact':<8}type",
                "-" * 72,
            ]
        )
        for index, row in enumerate(matches, start=1):
            lines.append(
                f"{index:<4}{row['p']:<8}{row['h']:<8}{row['s']:<12}{row['n']:<6}{row['Lmax']:<10}{row['closest_L']:<12}{row['m']:<8}{row['gap']:<8}{str(row['exact']).lower():<8}{row['base_type']}"
            )
        lines.extend(["-" * 72, "Use 'match apply <rank>' to load one of these configs into the active session."])
        return "\n".join(lines)


@dataclass
class MissionCell:
    cell_id: int
    row: int
    col: int
    ternary_code: str
    terrain: str
    hazard: int
    sample_value: int
    energy_value: int
    command_name: str
    command_label: str


@dataclass
class MissionState:
    ship_row: int
    ship_col: int
    cursor_row: int
    cursor_col: int
    home_row: int
    home_col: int
    target_row: Optional[int] = None
    target_col: Optional[int] = None
    oxygen: int = 100
    energy: int = 100
    hull: int = 100
    score: int = 0
    samples: int = 0
    discoveries: int = 0
    tick: int = 0
    autopilot: bool = False
    last_action: str = "Boot complete."
    beacons: list[tuple[int, int]] = field(default_factory=list)
    scanned_cells: list[int] = field(default_factory=list)
    visited_cells: list[int] = field(default_factory=list)


class AstronautMissionControl:
    COMMAND_DEFS = [
        ("hold_position", "HOLD"),
        ("thrust_north", "N"),
        ("thrust_south", "S"),
        ("thrust_east", "E"),
        ("thrust_west", "W"),
        ("scan_sector", "SCAN"),
        ("collect_sample", "SAMPLE"),
        ("repair_hull", "REPAIR"),
        ("recharge", "CHARGE"),
        ("deploy_beacon", "BEACON"),
        ("toggle_autopilot", "AUTO"),
        ("warp_home", "HOME"),
    ]
    TERRAIN = ["void", "regolith", "ice", "solar", "debris", "nebula", "station"]

    def __init__(self, runtime_dir: Path | str = DEFAULT_RUNTIME_DIR) -> None:
        self.runtime_dir = Path(runtime_dir)
        self.session = InfinitySession()
        self.cells: list[MissionCell] = []
        self.matrix_size = 0
        self.matrix_capacity = 0
        self.state: Optional[MissionState] = None
        self.random = random.Random(841)
        self.command_handlers: dict[str, Callable[[MissionCell], str]] = {
            "hold_position": self.cmd_hold_position,
            "thrust_north": self.cmd_thrust_north,
            "thrust_south": self.cmd_thrust_south,
            "thrust_east": self.cmd_thrust_east,
            "thrust_west": self.cmd_thrust_west,
            "scan_sector": self.cmd_scan_sector,
            "collect_sample": self.cmd_collect_sample,
            "repair_hull": self.cmd_repair_hull,
            "recharge": self.cmd_recharge,
            "deploy_beacon": self.cmd_deploy_beacon,
            "toggle_autopilot": self.cmd_toggle_autopilot,
            "warp_home": self.cmd_warp_home,
        }
        self.bootstrap_runtime()

    def bootstrap_runtime(self) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        (self.runtime_dir / "logs").mkdir(exist_ok=True)
        config_path = self.runtime_dir / "config.json"
        manifest_path = self.runtime_dir / "manifest.json"
        state_path = self.runtime_dir / "mission_state.json"
        matrix_path = self.runtime_dir / "mission_matrix.json"
        export_path = self.runtime_dir / "last_export.json"

        if config_path.exists():
            try:
                self.session.load_config(config_path)
            except Exception:
                self.session = InfinitySession()

        if matrix_path.exists() and state_path.exists():
            self.load_runtime()
            return

        self.session.paste_text(BOOTSTRAP_PAYLOAD, limit=12)
        self.session.match_apply(1)
        best_row = self.session.last_matches[0]
        self.matrix_capacity = int(best_row["closest_L"])
        self.matrix_size = math.isqrt(self.matrix_capacity)
        if self.matrix_size * self.matrix_size != self.matrix_capacity:
            raise RuntimeError("Bootstrap matrix capacity is not a perfect square.")
        self.cells = self.generate_cells(self.matrix_capacity, self.matrix_size)
        center = self.matrix_size // 2
        self.state = MissionState(
            ship_row=center,
            ship_col=center,
            cursor_row=center,
            cursor_col=center,
            home_row=center,
            home_col=center,
            visited_cells=[self.index_from_row_col(center, center)],
        )
        config_path.write_text(json.dumps(self.session.cfg, indent=2), encoding="utf-8")
        export_path.write_text(self.session.export_payload(), encoding="utf-8")
        self.write_matrix(matrix_path)
        self.save_state(state_path)
        manifest = {
            "name": "Astronaut",
            "runtime_dir": str(self.runtime_dir),
            "bootstrap": {
                "char_length": 841,
                "unique_count": 62,
                "matrix_capacity": self.matrix_capacity,
                "matrix_size": self.matrix_size,
                "ternary_address_width": 7,
            },
            "files": {
                "config": config_path.name,
                "matrix": matrix_path.name,
                "state": state_path.name,
                "export": export_path.name,
            },
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    def load_runtime(self) -> None:
        matrix = json.loads((self.runtime_dir / "mission_matrix.json").read_text(encoding="utf-8"))
        self.cells = [MissionCell(**row) for row in matrix["cells"]]
        self.matrix_size = int(matrix["matrix_size"])
        self.matrix_capacity = int(matrix["matrix_capacity"])
        state_payload = json.loads((self.runtime_dir / "mission_state.json").read_text(encoding="utf-8"))
        beacons = [tuple(item) for item in state_payload.get("beacons", [])]
        state_payload["beacons"] = beacons
        self.state = MissionState(**state_payload)

    def write_matrix(self, path: Path) -> None:
        payload = {
            "matrix_size": self.matrix_size,
            "matrix_capacity": self.matrix_capacity,
            "cells": [asdict(cell) for cell in self.cells],
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        readable = self.runtime_dir / "mission_matrix.txt"
        lines = [f"Astronaut mission matrix: {self.matrix_size}x{self.matrix_size} ({self.matrix_capacity} cells)"]
        for cell in self.cells:
            lines.append(
                f"{cell.cell_id:03d} row={cell.row:02d} col={cell.col:02d} code={cell.ternary_code} terrain={cell.terrain} hazard={cell.hazard} sample={cell.sample_value} cmd={cell.command_name}"
            )
        readable.write_text("\n".join(lines), encoding="utf-8")

    def save_state(self, path: Optional[Path] = None) -> None:
        if self.state is None:
            return
        target = path or (self.runtime_dir / "mission_state.json")
        target.write_text(json.dumps(asdict(self.state), indent=2), encoding="utf-8")
        (self.runtime_dir / "config.json").write_text(json.dumps(self.session.cfg, indent=2), encoding="utf-8")
        (self.runtime_dir / "last_export.json").write_text(self.session.export_payload(), encoding="utf-8")

    def reset_mission(self) -> str:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        for filename in ["mission_matrix.json", "mission_matrix.txt", "mission_state.json", "config.json", "manifest.json", "last_export.json"]:
            path = self.runtime_dir / filename
            if path.exists():
                path.unlink()
        self.session = InfinitySession()
        self.cells = []
        self.matrix_size = 0
        self.matrix_capacity = 0
        self.state = None
        self.bootstrap_runtime()
        return "Mission reset and runtime regenerated."

    def generate_cells(self, capacity: int, size: int) -> list[MissionCell]:
        cells: list[MissionCell] = []
        width = 7
        for cell_id in range(capacity):
            row, col = divmod(cell_id, size)
            ternary = self.to_base3(cell_id, width)
            digits = [int(ch) for ch in ternary]
            digit_sum = sum(digits)
            terrain = self.TERRAIN[digit_sum % len(self.TERRAIN)]
            hazard = (digit_sum + digits[0] * 2 + digits[-1]) % 6
            sample_value = (digits[1] * 3 + digits[3] * 2 + digits[5]) % 9
            energy_value = (digits[0] + digits[2] + digits[4] + digits[6]) % 7
            command_name, command_label = self.COMMAND_DEFS[digit_sum % len(self.COMMAND_DEFS)]
            cells.append(
                MissionCell(
                    cell_id=cell_id,
                    row=row,
                    col=col,
                    ternary_code=ternary,
                    terrain=terrain,
                    hazard=hazard,
                    sample_value=sample_value,
                    energy_value=energy_value,
                    command_name=command_name,
                    command_label=command_label,
                )
            )
        return cells

    @staticmethod
    def to_base3(value: int, width: int) -> str:
        digits = ["0"] * width
        number = value
        for index in range(width - 1, -1, -1):
            digits[index] = str(number % 3)
            number //= 3
        return "".join(digits)

    def cell_at(self, row: int, col: int) -> MissionCell:
        return self.cells[self.index_from_row_col(row, col)]

    def cell_by_id(self, cell_id: int) -> MissionCell:
        if cell_id < 0 or cell_id >= len(self.cells):
            raise ValueError("Cell ID out of range.")
        return self.cells[cell_id]

    def index_from_row_col(self, row: int, col: int) -> int:
        row = max(0, min(self.matrix_size - 1, row))
        col = max(0, min(self.matrix_size - 1, col))
        return row * self.matrix_size + col

    def current_cell(self) -> MissionCell:
        if self.state is None:
            raise RuntimeError("Mission state not initialised.")
        return self.cell_at(self.state.ship_row, self.state.ship_col)

    def cursor_cell(self) -> MissionCell:
        if self.state is None:
            raise RuntimeError("Mission state not initialised.")
        return self.cell_at(self.state.cursor_row, self.state.cursor_col)

    def mission_status(self) -> str:
        if self.state is None:
            raise RuntimeError("Mission state not initialised.")
        ship = self.current_cell()
        cursor = self.cursor_cell()
        lines = [
            f"mission                : Astronaut",
            f"matrix                 : {self.matrix_size}x{self.matrix_size} ({self.matrix_capacity} cells)",
            f"ship                   : row={self.state.ship_row} col={self.state.ship_col} cell={ship.cell_id} code={ship.ternary_code}",
            f"cursor                 : row={self.state.cursor_row} col={self.state.cursor_col} cell={cursor.cell_id} code={cursor.ternary_code}",
            f"oxygen / energy / hull : {self.state.oxygen} / {self.state.energy} / {self.state.hull}",
            f"score / samples        : {self.state.score} / {self.state.samples}",
            f"discoveries            : {self.state.discoveries}",
            f"autopilot              : {'on' if self.state.autopilot else 'off'}",
            f"target                 : {self.format_target()}",
            f"last action            : {self.state.last_action}",
            f"ship terrain           : {ship.terrain} (hazard={ship.hazard}, sample={ship.sample_value}, energy={ship.energy_value})",
            f"cursor command         : {cursor.command_name} [{cursor.command_label}]",
        ]
        return "\n".join(lines)

    def format_target(self) -> str:
        if self.state is None:
            return "n/a"
        if self.state.target_row is None or self.state.target_col is None:
            return "none"
        target = self.cell_at(self.state.target_row, self.state.target_col)
        return f"row={target.row} col={target.col} cell={target.cell_id}"

    def mission_matrix_window(self, radius: int = 2) -> str:
        if self.state is None:
            raise RuntimeError("Mission state not initialised.")
        radius = max(1, radius)
        r0 = max(0, self.state.cursor_row - radius)
        r1 = min(self.matrix_size - 1, self.state.cursor_row + radius)
        c0 = max(0, self.state.cursor_col - radius)
        c1 = min(self.matrix_size - 1, self.state.cursor_col + radius)
        lines = [f"matrix window around cursor ({self.state.cursor_row}, {self.state.cursor_col})"]
        for row in range(r0, r1 + 1):
            parts = []
            for col in range(c0, c1 + 1):
                cell = self.cell_at(row, col)
                marker = "."
                if row == self.state.ship_row and col == self.state.ship_col:
                    marker = "A"
                if row == self.state.cursor_row and col == self.state.cursor_col:
                    marker = "C"
                if row == self.state.ship_row and col == self.state.ship_col and row == self.state.cursor_row and col == self.state.cursor_col:
                    marker = "@"
                parts.append(f"{marker}{cell.command_label[:2]:<2}{cell.hazard}")
            lines.append(f"r{row:02d}: " + " ".join(parts))
        lines.append("legend: @ ship+cursor, A ship, C cursor, last digit = hazard")
        return "\n".join(lines)

    def move_cursor(self, row: int, col: int) -> str:
        if self.state is None:
            raise RuntimeError("Mission state not initialised.")
        self.state.cursor_row = max(0, min(self.matrix_size - 1, row))
        self.state.cursor_col = max(0, min(self.matrix_size - 1, col))
        self.state.last_action = f"Cursor moved to row={self.state.cursor_row}, col={self.state.cursor_col}."
        self.save_state()
        return self.state.last_action

    def select_cell(self, cell_id: int) -> str:
        cell = self.cell_by_id(cell_id)
        return self.move_cursor(cell.row, cell.col)

    def set_target(self, row: int, col: int) -> str:
        if self.state is None:
            raise RuntimeError("Mission state not initialised.")
        self.state.target_row = max(0, min(self.matrix_size - 1, row))
        self.state.target_col = max(0, min(self.matrix_size - 1, col))
        self.state.last_action = f"Autopilot target set to row={self.state.target_row}, col={self.state.target_col}."
        self.save_state()
        return self.state.last_action

    def execute_current(self) -> str:
        return self.execute_cell(self.cursor_cell())

    def execute_by_id(self, cell_id: int) -> str:
        return self.execute_cell(self.cell_by_id(cell_id))

    def execute_cell(self, cell: MissionCell) -> str:
        if self.state is None:
            raise RuntimeError("Mission state not initialised.")
        handler = self.command_handlers[cell.command_name]
        outcome = handler(cell)
        self.apply_environment(cell)
        self.state.last_action = f"Executed cell {cell.cell_id} [{cell.command_name}] -> {outcome}"
        self.tick_once(passive=False)
        self.save_state()
        return self.state.last_action

    def tick_once(self, passive: bool = True) -> None:
        if self.state is None:
            raise RuntimeError("Mission state not initialised.")
        self.state.tick += 1
        self.state.oxygen = max(0, self.state.oxygen - 1)
        self.state.energy = max(0, self.state.energy - (1 if passive else 2))
        if self.state.autopilot and self.state.target_row is not None and self.state.target_col is not None:
            self.autopilot_step()
        self.state.hull = max(0, min(100, self.state.hull))
        self.state.energy = max(0, min(100, self.state.energy))
        self.state.oxygen = max(0, min(100, self.state.oxygen))

    def step(self, ticks: int = 1) -> str:
        if self.state is None:
            raise RuntimeError("Mission state not initialised.")
        ticks = max(1, ticks)
        for _ in range(ticks):
            self.tick_once(passive=True)
        ship = self.current_cell()
        self.state.last_action = f"Advanced simulation by {ticks} tick(s). Ship at cell {ship.cell_id}."
        self.save_state()
        return self.state.last_action

    def autopilot_step(self) -> None:
        if self.state is None or self.state.target_row is None or self.state.target_col is None:
            return
        dr = self.state.target_row - self.state.ship_row
        dc = self.state.target_col - self.state.ship_col
        if dr == 0 and dc == 0:
            return
        if abs(dr) >= abs(dc):
            self.state.ship_row += 1 if dr > 0 else -1
        else:
            self.state.ship_col += 1 if dc > 0 else -1
        self.state.ship_row = max(0, min(self.matrix_size - 1, self.state.ship_row))
        self.state.ship_col = max(0, min(self.matrix_size - 1, self.state.ship_col))
        idx = self.index_from_row_col(self.state.ship_row, self.state.ship_col)
        if idx not in self.state.visited_cells:
            self.state.visited_cells.append(idx)
        self.apply_environment(self.current_cell())

    def apply_environment(self, cell: MissionCell) -> None:
        if self.state is None:
            raise RuntimeError("Mission state not initialised.")
        if cell.hazard > 0:
            self.state.hull = max(0, self.state.hull - cell.hazard)
        if cell.energy_value > 0 and cell.terrain in {"solar", "station"}:
            self.state.energy = min(100, self.state.energy + cell.energy_value)
        idx = cell.cell_id
        if idx not in self.state.visited_cells:
            self.state.visited_cells.append(idx)
            self.state.score += 1

    def cmd_hold_position(self, cell: MissionCell) -> str:
        if self.state is None:
            raise RuntimeError("Mission state not initialised.")
        self.state.energy = min(100, self.state.energy + 1)
        return "stability hold engaged"

    def _move_ship(self, dr: int, dc: int, label: str) -> str:
        if self.state is None:
            raise RuntimeError("Mission state not initialised.")
        self.state.ship_row = max(0, min(self.matrix_size - 1, self.state.ship_row + dr))
        self.state.ship_col = max(0, min(self.matrix_size - 1, self.state.ship_col + dc))
        self.state.energy = max(0, self.state.energy - 3)
        ship = self.current_cell()
        return f"{label} to cell {ship.cell_id}"

    def cmd_thrust_north(self, cell: MissionCell) -> str:
        return self._move_ship(-1, 0, "thrust north")

    def cmd_thrust_south(self, cell: MissionCell) -> str:
        return self._move_ship(1, 0, "thrust south")

    def cmd_thrust_east(self, cell: MissionCell) -> str:
        return self._move_ship(0, 1, "thrust east")

    def cmd_thrust_west(self, cell: MissionCell) -> str:
        return self._move_ship(0, -1, "thrust west")

    def cmd_scan_sector(self, cell: MissionCell) -> str:
        if self.state is None:
            raise RuntimeError("Mission state not initialised.")
        nearby: list[MissionCell] = []
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                row = max(0, min(self.matrix_size - 1, self.state.ship_row + dr))
                col = max(0, min(self.matrix_size - 1, self.state.ship_col + dc))
                nearby.append(self.cell_at(row, col))
        highest_hazard = max(item.hazard for item in nearby)
        sample_sum = sum(item.sample_value for item in nearby)
        for item in nearby:
            if item.cell_id not in self.state.scanned_cells:
                self.state.scanned_cells.append(item.cell_id)
        self.state.discoveries += 1
        self.state.score += 2
        return f"scan complete: hazard_peak={highest_hazard}, sample_sum={sample_sum}"

    def cmd_collect_sample(self, cell: MissionCell) -> str:
        if self.state is None:
            raise RuntimeError("Mission state not initialised.")
        ship = self.current_cell()
        gain = max(1, ship.sample_value)
        self.state.samples += gain
        self.state.score += gain * 2
        self.state.energy = max(0, self.state.energy - 2)
        return f"collected sample value {gain}"

    def cmd_repair_hull(self, cell: MissionCell) -> str:
        if self.state is None:
            raise RuntimeError("Mission state not initialised.")
        repair = min(12, max(0, self.state.energy // 5))
        self.state.hull = min(100, self.state.hull + repair)
        self.state.energy = max(0, self.state.energy - repair)
        return f"repaired hull by {repair}"

    def cmd_recharge(self, cell: MissionCell) -> str:
        if self.state is None:
            raise RuntimeError("Mission state not initialised.")
        ship = self.current_cell()
        gain = 8 + ship.energy_value
        if ship.row == self.state.home_row and ship.col == self.state.home_col:
            gain += 12
        self.state.energy = min(100, self.state.energy + gain)
        self.state.oxygen = min(100, self.state.oxygen + 4)
        return f"recharged energy by {gain}"

    def cmd_deploy_beacon(self, cell: MissionCell) -> str:
        if self.state is None:
            raise RuntimeError("Mission state not initialised.")
        marker = (self.state.ship_row, self.state.ship_col)
        if marker not in self.state.beacons:
            self.state.beacons.append(marker)
            self.state.score += 3
            return f"deployed beacon at {marker}"
        return f"beacon already present at {marker}"

    def cmd_toggle_autopilot(self, cell: MissionCell) -> str:
        if self.state is None:
            raise RuntimeError("Mission state not initialised.")
        self.state.autopilot = not self.state.autopilot
        if self.state.autopilot:
            self.state.target_row = self.state.cursor_row
            self.state.target_col = self.state.cursor_col
        return f"autopilot {'enabled' if self.state.autopilot else 'disabled'}"

    def cmd_warp_home(self, cell: MissionCell) -> str:
        if self.state is None:
            raise RuntimeError("Mission state not initialised.")
        if self.state.energy < 20:
            return "warp aborted: insufficient energy"
        self.state.ship_row = self.state.home_row
        self.state.ship_col = self.state.home_col
        self.state.energy -= 20
        self.state.oxygen = min(100, self.state.oxygen + 10)
        return "warp complete: home position reached"

    def run_graphical(self) -> int:
        if pygame is None:
            print("pygame is not available in this environment.")
            return 1
        if self.state is None:
            print("Mission state not initialised.")
            return 1

        pygame.init()
        cell_size = 24
        sidebar = 260
        width = self.matrix_size * cell_size + sidebar
        height = self.matrix_size * cell_size
        screen = pygame.display.set_mode((width, height))
        pygame.display.set_caption("Astronaut Mission Control")
        font = pygame.font.SysFont(None, 20)
        clock = pygame.time.Clock()
        colors = {
            "void": (25, 25, 45),
            "regolith": (110, 95, 70),
            "ice": (150, 190, 220),
            "solar": (180, 150, 40),
            "debris": (90, 90, 90),
            "nebula": (85, 45, 105),
            "station": (60, 120, 120),
            "grid": (30, 30, 30),
            "cursor": (255, 255, 255),
            "ship": (50, 220, 90),
            "home": (90, 180, 255),
            "beacon": (255, 130, 40),
            "text": (235, 235, 235),
            "hazard": (220, 80, 80),
            "background": (14, 16, 20),
        }
        running = True
        last_auto = time.time()
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key in (pygame.K_LEFT, pygame.K_a):
                        self.move_cursor(self.state.cursor_row, self.state.cursor_col - 1)
                    elif event.key in (pygame.K_RIGHT, pygame.K_d):
                        self.move_cursor(self.state.cursor_row, self.state.cursor_col + 1)
                    elif event.key in (pygame.K_UP, pygame.K_w):
                        self.move_cursor(self.state.cursor_row - 1, self.state.cursor_col)
                    elif event.key in (pygame.K_DOWN, pygame.K_s):
                        self.move_cursor(self.state.cursor_row + 1, self.state.cursor_col)
                    elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                        self.execute_current()
                    elif event.key == pygame.K_t:
                        self.set_target(self.state.cursor_row, self.state.cursor_col)
                    elif event.key == pygame.K_g:
                        self.step(1)
                    elif event.key == pygame.K_r:
                        self.reset_mission()
                    elif event.key == pygame.K_TAB:
                        self.move_cursor(self.state.ship_row, self.state.ship_col)
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    x, y = event.pos
                    if x < self.matrix_size * cell_size and y < self.matrix_size * cell_size:
                        col = x // cell_size
                        row = y // cell_size
                        self.move_cursor(row, col)

            if self.state.autopilot and time.time() - last_auto >= 0.3:
                self.step(1)
                last_auto = time.time()

            screen.fill(colors["background"])
            for cell in self.cells:
                x = cell.col * cell_size
                y = cell.row * cell_size
                rect = pygame.Rect(x, y, cell_size, cell_size)
                pygame.draw.rect(screen, colors[cell.terrain], rect)
                pygame.draw.rect(screen, colors["grid"], rect, 1)
                if cell.hazard >= 4:
                    pygame.draw.circle(screen, colors["hazard"], rect.center, max(2, cell_size // 7))
            for beacon_row, beacon_col in self.state.beacons:
                bx = beacon_col * cell_size + cell_size // 2
                by = beacon_row * cell_size + cell_size // 2
                pygame.draw.circle(screen, colors["beacon"], (bx, by), max(3, cell_size // 5), 2)
            home_rect = pygame.Rect(self.state.home_col * cell_size, self.state.home_row * cell_size, cell_size, cell_size)
            pygame.draw.rect(screen, colors["home"], home_rect, 2)
            ship_rect = pygame.Rect(self.state.ship_col * cell_size + 4, self.state.ship_row * cell_size + 4, cell_size - 8, cell_size - 8)
            pygame.draw.rect(screen, colors["ship"], ship_rect)
            cursor_rect = pygame.Rect(self.state.cursor_col * cell_size + 1, self.state.cursor_row * cell_size + 1, cell_size - 2, cell_size - 2)
            pygame.draw.rect(screen, colors["cursor"], cursor_rect, 2)
            sidebar_x = self.matrix_size * cell_size + 12
            info = [
                "Astronaut Mission Control",
                f"tick: {self.state.tick}",
                f"oxygen: {self.state.oxygen}",
                f"energy: {self.state.energy}",
                f"hull: {self.state.hull}",
                f"score: {self.state.score}",
                f"samples: {self.state.samples}",
                f"autopilot: {'on' if self.state.autopilot else 'off'}",
                f"cursor cell: {self.cursor_cell().cell_id}",
                f"command: {self.cursor_cell().command_name}",
                f"target: {self.format_target()}",
                "",
                "Keys:",
                "WASD / arrows: move cursor",
                "Space / Enter: execute cell",
                "T: set target to cursor",
                "G: advance one tick",
                "Tab: snap cursor to ship",
                "R: regenerate runtime",
                "",
                textwrap.shorten(self.state.last_action, width=30, placeholder="..."),
            ]
            for idx, line in enumerate(info):
                surf = font.render(line, True, colors["text"])
                screen.blit(surf, (sidebar_x, 16 + idx * 20))
            pygame.display.flip()
            clock.tick(60)
        self.save_state()
        pygame.quit()
        return 0

    def handle_command(self, line: str) -> str:
        parts = shlex.split(line)
        if not parts:
            return ""
        cmd = parts[0].lower()
        try:
            if cmd in {"help", "commands"}:
                return self.session.help_text()
            if cmd == "explain":
                if len(parts) < 2:
                    return "Usage: explain <topic>"
                return self.session.explain(" ".join(parts[1:]))
            if cmd == "show":
                return self.session.show()
            if cmd == "set":
                if len(parts) < 3:
                    return "Usage: set <key> <value>"
                result = self.session.set_value(parts[1], parts[2])
                self.save_state()
                return result
            if cmd == "reset":
                result = self.session.reset()
                self.save_state()
                return result
            if cmd == "classify":
                return self.session.classify()
            if cmd == "lengths":
                return self.session.lengths(int(parts[1]) if len(parts) > 1 else None)
            if cmd == "fabric":
                if len(parts) < 2 or parts[1].lower() != "traverse":
                    return "Usage: fabric traverse"
                return self.session.fabric_traverse()
            if cmd == "witness":
                if len(parts) < 2:
                    return "Usage: witness <L>"
                return self.session.witness(int(parts[1]))
            if cmd == "paste":
                limit = int(parts[1]) if len(parts) > 1 else None
                print("Paste multiline text. End with a line containing only .end")
                print("Enter .cancel on its own line to abort.")
                lines: list[str] = []
                while True:
                    next_line = input("... ")
                    if next_line == ".cancel":
                        return "Paste cancelled."
                    if next_line == ".end":
                        break
                    lines.append(next_line)
                return self.session.paste_text("\n".join(lines), limit)
            if cmd == "match":
                if len(parts) < 3:
                    return "Usage: match apply <rank> | match refine <rank>"
                if parts[1].lower() == "apply":
                    result = self.session.match_apply(int(parts[2]))
                    self.save_state()
                    return result
                if parts[1].lower() == "refine":
                    return self.session.match_refine(int(parts[2]))
                return "Usage: match apply <rank> | match refine <rank>"
            if cmd == "save":
                path = self.runtime_dir / (parts[1] if len(parts) > 1 else "ndcodex_config.json")
                return self.session.save_config(path)
            if cmd == "load":
                path = self.runtime_dir / (parts[1] if len(parts) > 1 else "ndcodex_config.json")
                result = self.session.load_config(path)
                self.save_state()
                return result
            if cmd == "export":
                if len(parts) > 1:
                    path = self.runtime_dir / parts[1]
                    return self.session.export_payload(path)
                return self.session.export_payload()
            if cmd in {"quit", "exit"}:
                raise SystemExit(0)
            if cmd == "mission":
                if len(parts) < 2:
                    return "Usage: mission <status|matrix|select|goto|execute|step|reset|launch>"
                sub = parts[1].lower()
                if sub == "status":
                    return self.mission_status()
                if sub == "matrix":
                    radius = int(parts[2]) if len(parts) > 2 else 2
                    return self.mission_matrix_window(radius)
                if sub == "select":
                    if len(parts) < 3:
                        return "Usage: mission select <cell_id>"
                    return self.select_cell(int(parts[2]))
                if sub == "goto":
                    if len(parts) < 4:
                        return "Usage: mission goto <row> <col>"
                    return self.set_target(int(parts[2]), int(parts[3]))
                if sub == "execute":
                    if len(parts) > 2:
                        return self.execute_by_id(int(parts[2]))
                    return self.execute_current()
                if sub == "step":
                    ticks = int(parts[2]) if len(parts) > 2 else 1
                    return self.step(ticks)
                if sub == "reset":
                    return self.reset_mission()
                if sub == "launch":
                    return "Launching graphical mission control..."
                return "Usage: mission <status|matrix|select|goto|execute|step|reset|launch>"
            return "Unknown command. Type 'help' or 'commands'."
        except SystemExit:
            raise
        except Exception as exc:
            return f"[error] {exc}"

    def repl(self) -> int:
        print("=" * 72)
        print("Astronaut mission control")
        print("=" * 72)
        print("Type 'help' or 'commands' for the command list.")
        print("Type 'mission status' to inspect the current simulation.")
        while True:
            try:
                line = input("Astronaut> ").strip()
            except EOFError:
                print()
                return 0
            if not line:
                continue
            if line == "mission launch":
                return self.run_graphical()
            try:
                output = self.handle_command(line)
            except SystemExit as exc:
                return int(exc.code)
            if output:
                print(output)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Astronaut mission control")
    parser.add_argument("--runtime-dir", default=str(DEFAULT_RUNTIME_DIR), help="Directory used for generated runtime files.")
    parser.add_argument("--gui", action="store_true", help="Launch the graphical mission-control window.")
    parser.add_argument("--status", action="store_true", help="Print mission status and exit.")
    parser.add_argument("--command", help="Run one command and exit.")
    parser.add_argument("--reset-runtime", action="store_true", help="Regenerate the runtime before doing anything else.")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    control = AstronautMissionControl(args.runtime_dir)
    if args.reset_runtime:
        print(control.reset_mission())
    if args.status:
        print(control.mission_status())
        return 0
    if args.command:
        if args.command == "mission launch" or args.gui:
            return control.run_graphical()
        output = control.handle_command(args.command)
        if output:
            print(output)
        return 0
    if args.gui:
        return control.run_graphical()
    return control.repl()


if __name__ == "__main__":
    raise SystemExit(main())
