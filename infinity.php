<?php
declare(strict_types=1);

/**
 * nDCodex.php
 *
 * CLI REPL for n-dimensional hash-length fabric analysis.
 *
 * Main additions in this revision:
 * - multiline paste mode for code/text analysis
 * - ranked config matching based on:
 *   - observed unique characters
 *   - pasted character length
 *   - active dimension n
 * - match application back into the active session
 */

if (PHP_SAPI !== 'cli') {
    header('Content-Type: text/html; charset=utf-8');
    echo '<!doctype html><html><head><meta charset="utf-8"><title>nDCodex.php</title>';
    echo '<style>body{font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:860px;margin:40px auto;padding:0 16px;line-height:1.5}code,pre{font-family:Consolas,monospace;background:#f4f4f4;padding:2px 4px}pre{padding:12px;overflow:auto}</style>';
    echo '</head><body>';
    echo '<h1>nDCodex.php</h1>';
    echo '<p>This file is a CLI REPL. Run it from a terminal:</p>';
    echo '<pre>php nDCodex.php</pre>';
    echo '<p>Then use:</p>';
    echo '<pre>paste\n.end</pre>';
    echo '</body></html>';
    exit;
}

final class BigDec
{
    /** @var array<string,string> */
    private static array $powCache = [];

    public static function norm(string $n): string
    {
        $n = ltrim($n, '0');
        return $n === '' ? '0' : $n;
    }

    public static function cmp(string $a, string $b): int
    {
        $a = self::norm($a);
        $b = self::norm($b);
        $la = strlen($a);
        $lb = strlen($b);
        if ($la !== $lb) {
            return $la <=> $lb;
        }
        return $a <=> $b;
    }

    public static function mulInt(string $a, int $m): string
    {
        if ($m < 0) {
            throw new InvalidArgumentException('Negative multiplier not supported.');
        }
        $a = self::norm($a);
        if ($a === '0' || $m === 0) {
            return '0';
        }
        if ($m === 1) {
            return $a;
        }
        $carry = 0;
        $out = '';
        for ($i = strlen($a) - 1; $i >= 0; --$i) {
            $digit = ord($a[$i]) - 48;
            $prod = $digit * $m + $carry;
            $out = (string)($prod % 10) . $out;
            $carry = intdiv($prod, 10);
        }
        while ($carry > 0) {
            $out = (string)($carry % 10) . $out;
            $carry = intdiv($carry, 10);
        }
        return self::norm($out);
    }

    public static function powInt(int $base, int $exp): string
    {
        if ($base < 0 || $exp < 0) {
            throw new InvalidArgumentException('Base and exponent must be non-negative.');
        }
        $key = $base . '^' . $exp;
        if (isset(self::$powCache[$key])) {
            return self::$powCache[$key];
        }
        $result = '1';
        for ($i = 0; $i < $exp; ++$i) {
            $result = self::mulInt($result, $base);
        }
        self::$powCache[$key] = $result;
        return $result;
    }
}

final class MathUtil
{
    public static function boundedPow(int $base, int $exp, int $limit): int
    {
        $result = 1;
        for ($i = 0; $i < $exp; ++$i) {
            if ($base !== 0 && $result > intdiv($limit, max(1, $base))) {
                return $limit + 1;
            }
            $result *= $base;
            if ($result > $limit) {
                return $limit + 1;
            }
        }
        return $result;
    }

    public static function exactNthRoot(int $x, int $n): ?int
    {
        if ($n <= 0 || $x < 0) {
            throw new InvalidArgumentException('Invalid nth-root arguments.');
        }
        if ($x === 0 || $x === 1) {
            return $x;
        }
        $lo = 1;
        $hi = $x;
        while ($lo <= $hi) {
            $mid = intdiv($lo + $hi, 2);
            $pow = self::boundedPow($mid, $n, $x);
            if ($pow === $x) {
                return $mid;
            }
            if ($pow < $x) {
                $lo = $mid + 1;
            } else {
                $hi = $mid - 1;
            }
        }
        return null;
    }

    public static function nthRootFloor(int $x, int $n): int
    {
        if ($n <= 0 || $x < 0) {
            throw new InvalidArgumentException('Invalid nth-root arguments.');
        }
        if ($x === 0 || $x === 1) {
            return $x;
        }
        $lo = 1;
        $hi = $x;
        $best = 1;
        while ($lo <= $hi) {
            $mid = intdiv($lo + $hi, 2);
            $pow = self::boundedPow($mid, $n, $x);
            if ($pow === $x) {
                return $mid;
            }
            if ($pow < $x) {
                $best = $mid;
                $lo = $mid + 1;
            } else {
                $hi = $mid - 1;
            }
        }
        return $best;
    }

    /** @return array{valid:bool,m:?int} */
    public static function validLengthInfo(int $L, int $n, int $minRoot): array
    {
        $m = self::exactNthRoot($L, $n);
        return [
            'valid' => $m !== null && $m >= $minRoot,
            'm' => $m,
        ];
    }

    public static function nearestValidLength(int $target, int $n, int $minRoot, int $Lmax): array
    {
        if ($target < 1 || $Lmax < 1) {
            return [
                'closest_L' => null,
                'm' => null,
                'gap' => null,
                'exact' => false,
                'below_L' => null,
                'above_L' => null,
            ];
        }

        $exact = self::validLengthInfo($target, $n, $minRoot);
        if ($exact['valid'] && $target <= $Lmax) {
            return [
                'closest_L' => $target,
                'm' => $exact['m'],
                'gap' => 0,
                'exact' => true,
                'below_L' => $target,
                'above_L' => $target,
            ];
        }

        $rootFloor = self::nthRootFloor($target, $n);
        $candidates = [];
        $start = max($minRoot, $rootFloor - 3);
        $end = $rootFloor + 4;
        for ($m = $start; $m <= $end; ++$m) {
            $L = self::boundedPow($m, $n, PHP_INT_MAX >> 4);
            if ($L >= 1 && $L <= $Lmax) {
                $candidates[$L] = $m;
            }
        }

        if ($candidates === []) {
            $maxRoot = self::nthRootFloor($Lmax, $n);
            if ($maxRoot >= $minRoot) {
                $L = self::boundedPow($maxRoot, $n, PHP_INT_MAX >> 4);
                return [
                    'closest_L' => $L,
                    'm' => $maxRoot,
                    'gap' => abs($L - $target),
                    'exact' => false,
                    'below_L' => $L,
                    'above_L' => null,
                ];
            }
            return [
                'closest_L' => null,
                'm' => null,
                'gap' => null,
                'exact' => false,
                'below_L' => null,
                'above_L' => null,
            ];
        }

        ksort($candidates);
        $bestL = null;
        $bestM = null;
        $bestGap = null;
        $below = null;
        $above = null;
        foreach ($candidates as $L => $m) {
            if ($L <= $target) {
                $below = $L;
            }
            if ($L >= $target && $above === null) {
                $above = $L;
            }
            $gap = abs($L - $target);
            if ($bestGap === null || $gap < $bestGap || ($gap === $bestGap && $L > (int)$bestL)) {
                $bestGap = $gap;
                $bestL = $L;
                $bestM = $m;
            }
        }

        return [
            'closest_L' => $bestL,
            'm' => $bestM,
            'gap' => $bestGap,
            'exact' => false,
            'below_L' => $below,
            'above_L' => $above,
        ];
    }

    public static function classifyBase(int $p): string
    {
        if ($p < 2) {
            return 'invalid';
        }
        if ($p === 2) {
            return 'prime';
        }
        if ($p % 2 === 0) {
            return 'other';
        }
        $r = (int)floor(sqrt((float)$p));
        for ($k = 3; $k <= $r; $k += 2) {
            if ($p % $k === 0) {
                return 'other';
            }
        }
        return 'prime';
    }

    /** @return list<int> */
    public static function centeredIntegers(int $center, int $min, int $max, int $limit): array
    {
        $out = [];
        $seen = [];
        $push = static function (int $v) use (&$out, &$seen, $min, $max, $limit): void {
            if ($v < $min || $v > $max || isset($seen[$v]) || count($out) >= $limit) {
                return;
            }
            $seen[$v] = true;
            $out[] = $v;
        };

        $push($center);
        for ($d = 1; count($out) < $limit && ($center - $d >= $min || $center + $d <= $max); ++$d) {
            $push($center - $d);
            $push($center + $d);
        }
        return $out;
    }
}

final class Fabric
{
    public static function maxPrimaryLength(int $h, int $s, int $p): int
    {
        if ($h < 2 || $s < 1 || $p < 2) {
            throw new InvalidArgumentException('Require h >= 2, s >= 1, p >= 2.');
        }
        $target = BigDec::powInt($h, $s);
        $lo = 1;
        $hi = 1;
        while (BigDec::cmp(BigDec::powInt($p, $hi), $target) < 0) {
            $hi *= 2;
        }
        while ($lo < $hi) {
            $mid = intdiv($lo + $hi, 2);
            if (BigDec::cmp(BigDec::powInt($p, $mid), $target) >= 0) {
                $hi = $mid;
            } else {
                $lo = $mid + 1;
            }
        }
        return $lo;
    }

    /** @return list<array{L:int,m:int}> */

    public static function maxPrimaryLengthApprox(int $h, int $s, int $p): int
    {
        if ($h < 2 || $s < 1 || $p < 2) {
            throw new InvalidArgumentException('Require h >= 2, s >= 1, p >= 2.');
        }
        $value = ((float)$s * log((float)$h)) / log((float)$p);
        $L = (int)ceil($value - 1e-12);
        return max(1, $L);
    }

    public static function validLengthsUpTo(int $Lmax, int $n, int $minRoot): array
    {
        $out = [];
        for ($L = 1; $L <= $Lmax; ++$L) {
            $info = MathUtil::validLengthInfo($L, $n, $minRoot);
            if ($info['valid']) {
                $out[] = ['L' => $L, 'm' => (int)$info['m']];
            }
        }
        return $out;
    }

    public static function minSecondaryLengthForPrimaryLength(int $h, int $p, int $L): int
    {
        if ($L < 1) {
            throw new InvalidArgumentException('L must be >= 1.');
        }
        $threshold = BigDec::powInt($p, $L - 1);
        $s = 1;
        while (BigDec::cmp(BigDec::powInt($h, $s), $threshold) <= 0) {
            ++$s;
        }
        return $s;
    }
}

final class TextAnalyzer
{
    /** @return array{chars:list<string>,char_length:int,unique_count:int,unique_chars:list<string>,line_count:int,preview:string} */
    public static function analyze(string $text): array
    {
        $chars = self::splitChars($text);
        $charLength = count($chars);
        $uniqueMap = [];
        foreach ($chars as $ch) {
            $uniqueMap[$ch] = true;
        }
        $uniqueChars = array_map(static fn ($x): string => (string)$x, array_keys($uniqueMap));
        usort($uniqueChars, static fn (string $a, string $b): int => $a <=> $b);

        $lineCount = $text === '' ? 0 : substr_count($text, "\n") + 1;
        return [
            'chars' => $chars,
            'char_length' => $charLength,
            'unique_count' => count($uniqueChars),
            'unique_chars' => $uniqueChars,
            'line_count' => $lineCount,
            'preview' => self::previewUniqueChars($uniqueChars),
        ];
    }

    /** @return list<string> */
    private static function splitChars(string $text): array
    {
        if ($text === '') {
            return [];
        }
        if (preg_match_all('/./us', $text, $m) !== false) {
            /** @var list<string> $chars */
            $chars = $m[0];
            return $chars;
        }
        return str_split($text);
    }

    /** @param list<string> $chars */
    private static function previewUniqueChars(array $chars): string
    {
        $parts = [];
        foreach ($chars as $ch) {
            $parts[] = self::escapeChar($ch);
            if (count($parts) >= 80) {
                break;
            }
        }
        return implode(' ', $parts);
    }

    public static function escapeChar(string $ch): string
    {
        return match ($ch) {
            "\n" => '\\n',
            "\r" => '\\r',
            "\t" => '\\t',
            ' ' => '<space>',
            default => $ch,
        };
    }
}

final class MatchEngine
{
    /**
     * @param array<string,mixed> $cfg
     * @param array{char_length:int,unique_count:int} $analysis
     * @return list<array<string,mixed>>
     */
    public static function rank(array $cfg, array $analysis, int $limit): array
    {
        $limit = max(1, min(12, $limit));
        $targetLength = max(1, (int)$analysis['char_length']);
        $observedUnique = max(1, (int)$analysis['unique_count']);

        $dimension = (int)$cfg['dimension'];
        $minRoot = (int)$cfg['min_root'];
        $primaryMin = max(2, (int)$cfg['match_primary_min']);
        $primaryMax = max($primaryMin, (int)$cfg['match_primary_max']);
        $hRadius = max(0, (int)$cfg['match_h_radius']);
        $pCandidates = MathUtil::centeredIntegers($observedUnique, $primaryMin, $primaryMax, max(24, $limit * 4));
        $hCandidates = MathUtil::centeredIntegers($observedUnique, max(2, $observedUnique - $hRadius), max(2, $observedUnique + $hRadius), max(1, 2 * $hRadius + 1));
        if ($hCandidates === []) {
            $hCandidates = [max(2, $observedUnique)];
        }

        $rows = [];
        foreach ($hCandidates as $h) {
            foreach ($pCandidates as $p) {
                $s = $targetLength;
                $Lmax = Fabric::maxPrimaryLength($h, $s, $p);
                $nearest = MathUtil::nearestValidLength($targetLength, $dimension, $minRoot, $Lmax);
                if ($nearest['closest_L'] === null) {
                    continue;
                }

                $gap = (int)$nearest['gap'];
                $closestL = (int)$nearest['closest_L'];
                $m = (int)$nearest['m'];
                $exact = (bool)$nearest['exact'];
                $hDelta = abs($h - $observedUnique);
                $pDelta = abs($p - $observedUnique);
                $score = ($exact ? -1000000 : 0) + $gap * 1000 + $hDelta * 100 + $pDelta;

                $rows[] = [
                    'score' => $score,
                    'p' => $p,
                    'h' => $h,
                    's' => $s,
                    'n' => $dimension,
                    'Lmax' => $Lmax,
                    'closest_L' => $closestL,
                    'm' => $m,
                    'gap' => $gap,
                    'exact' => $exact,
                    'base_type' => MathUtil::classifyBase($p),
                ];
            }
        }

        usort(
            $rows,
            static function (array $a, array $b): int {
                foreach (['score', 'gap', 'h', 'p'] as $key) {
                    if ($a[$key] < $b[$key]) {
                        return -1;
                    }
                    if ($a[$key] > $b[$key]) {
                        return 1;
                    }
                }
                return 0;
            }
        );

        $unique = [];
        $seen = [];
        foreach ($rows as $row) {
            $key = $row['p'] . '|' . $row['h'] . '|' . $row['s'] . '|' . $row['n'];
            if (isset($seen[$key])) {
                continue;
            }
            $seen[$key] = true;
            $unique[] = $row;
            if (count($unique) >= $limit) {
                break;
            }
        }
        return $unique;
    }
}

final class NDCodex
{
    /** @var array<string,mixed> */
    private array $cfg;

    /** @var array<string,mixed> */
    private array $last = [];

    /** @var list<array<string,mixed>> */
    private array $lastMatches = [];

    public function __construct()
    {
        $this->cfg = [
            'primary_alphabet' => 7,
            'secondary_alphabet' => 10,
            'secondary_length' => 5,
            'dimension' => 2,
            'min_root' => 2,
            'range_s_min' => 1,
            'range_s_max' => 12,
            'match_limit' => 12,
            'match_primary_min' => 2,
            'match_primary_max' => 128,
            'match_h_radius' => 0,
        ];
    }

    public function run(): void
    {
        $this->banner();
        while (true) {
            $line = $this->prompt('nDCodex> ');
            if ($line === null) {
                echo PHP_EOL;
                return;
            }
            $line = trim($line);
            if ($line === '') {
                continue;
            }
            $parts = preg_split('/\s+/', $line) ?: [];
            $cmd = strtolower((string)array_shift($parts));
            try {
                switch ($cmd) {
                    case 'help':
                        $this->help();
                        break;
                    case 'show':
                        $this->show();
                        break;
                    case 'set':
                        $this->setCommand($parts);
                        break;
                    case 'reset':
                        $this->__construct();
                        echo "Configuration reset.\n";
                        break;
                    case 'classify':
                        $this->classify();
                        break;
                    case 'lengths':
                        $this->lengthsCommand($parts);
                        break;
                    case 'fabric':
                        $this->fabricCommand($parts);
                        break;
                    case 'witness':
                        $this->witnessCommand($parts);
                        break;
                    case 'paste':
                        $this->pasteCommand($parts);
                        break;
                    case 'match':
                        $this->matchCommand($parts);
                        break;
                    case 'save':
                        $this->saveCommand($parts);
                        break;
                    case 'load':
                        $this->loadCommand($parts);
                        break;
                    case 'export':
                        $this->exportCommand($parts);
                        break;
                    case 'quit':
                    case 'exit':
                        return;
                    default:
                        echo "Unknown command. Type 'help'.\n";
                        break;
                }
            } catch (Throwable $e) {
                echo '[error] ' . $e->getMessage() . PHP_EOL;
            }
        }
    }

    private function banner(): void
    {
        echo str_repeat('=', 108) . PHP_EOL;
        echo "nDCodex.php — n-Dimensional Hash-Length Fabric REPL\n";
        echo str_repeat('=', 108) . PHP_EOL;
        echo "Type 'help' for commands.\n\n";
    }

    private function help(): void
    {
        echo <<<TXT
Commands
--------
help                       Show command list.
show                       Show current configuration.
set <key> <value>          Update configuration.
reset                      Reset configuration to defaults.
classify                   Classify the primary alphabet base.
lengths [s]                Show valid primary lengths for one secondary length.
fabric traverse            Traverse the configured secondary-length range.
witness <L>                Show the minimal secondary length able to realise L.
paste [limit]              Paste multiline code/text; end with .end.
match apply <rank>         Load a ranked paste-match config into the active session.
save [file.json]           Save configuration.
load [file.json]           Load configuration.
export [file.json]         Export last result payload.
quit | exit                Leave the REPL.

Keys
----
primary_alphabet   >= 2    primary output alphabet length p
secondary_alphabet >= 2    secondary input alphabet length h
secondary_length   >= 1    secondary string length s
dimension          >= 1    validity dimension n
min_root           >= 1    require L = m^n with m >= min_root
range_s_min        >= 1    start of traversal range
range_s_max        >= 1    end of traversal range
match_limit        1..12   default ranked results count
match_primary_min  >= 2    minimum candidate primary alphabet
match_primary_max  >= 2    maximum candidate primary alphabet
match_h_radius     >= 0    how far h may vary from observed unique chars
TXT;
        echo PHP_EOL;
    }

    private function show(): void
    {
        $p = (int)$this->cfg['primary_alphabet'];
        $h = (int)$this->cfg['secondary_alphabet'];
        $s = (int)$this->cfg['secondary_length'];
        $n = (int)$this->cfg['dimension'];
        $minRoot = (int)$this->cfg['min_root'];
        $Lmax = Fabric::maxPrimaryLength($h, $s, $p);
        $valid = Fabric::validLengthsUpTo($Lmax, $n, $minRoot);

        echo str_repeat('-', 108) . PHP_EOL;
        foreach ($this->cfg as $k => $v) {
            echo str_pad($k, 22) . ' : ' . (is_bool($v) ? ($v ? 'true' : 'false') : (string)$v) . PHP_EOL;
        }
        echo str_repeat('-', 108) . PHP_EOL;
        echo 'base classification     : ' . MathUtil::classifyBase($p) . PHP_EOL;
        echo 'max primary length      : ' . $Lmax . PHP_EOL;
        echo 'valid lengths @ s=' . $s . '    : ' . $this->formatValidList($valid) . PHP_EOL;
        echo 'fabric rule             : L is valid iff L = m^n and m >= min_root' . PHP_EOL;
        echo str_repeat('-', 108) . PHP_EOL;
    }

    private function setCommand(array $parts): void
    {
        if (count($parts) < 2) {
            throw new InvalidArgumentException('Usage: set <key> <value>');
        }
        $key = (string)$parts[0];
        $value = implode(' ', array_slice($parts, 1));
        if (!array_key_exists($key, $this->cfg)) {
            throw new InvalidArgumentException('Unknown key: ' . $key);
        }
        $this->cfg[$key] = $this->coerceValue($this->cfg[$key], $value);
        $this->validateConfig();
        echo 'Updated ' . $key . '.' . PHP_EOL;
    }

    private function classify(): void
    {
        $p = (int)$this->cfg['primary_alphabet'];
        echo 'primary_alphabet=' . $p . ' is ' . MathUtil::classifyBase($p) . PHP_EOL;
    }

    private function lengthsCommand(array $parts): void
    {
        $s = isset($parts[0]) ? max(1, (int)$parts[0]) : (int)$this->cfg['secondary_length'];
        $h = (int)$this->cfg['secondary_alphabet'];
        $p = (int)$this->cfg['primary_alphabet'];
        $n = (int)$this->cfg['dimension'];
        $minRoot = (int)$this->cfg['min_root'];

        $Lmax = Fabric::maxPrimaryLength($h, $s, $p);
        $valid = Fabric::validLengthsUpTo($Lmax, $n, $minRoot);

        echo 'secondary length s      : ' . $s . PHP_EOL;
        echo 'max primary length      : ' . $Lmax . PHP_EOL;
        echo 'valid primary lengths   : ' . $this->formatValidList($valid) . PHP_EOL;

        $this->last = [
            'type' => 'lengths',
            'secondary_length' => $s,
            'Lmax' => $Lmax,
            'valid' => $valid,
            'config' => $this->cfg,
        ];
    }

    private function fabricCommand(array $parts): void
    {
        $sub = strtolower((string)($parts[0] ?? 'traverse'));
        if ($sub !== 'traverse') {
            throw new InvalidArgumentException('Usage: fabric traverse');
        }

        $h = (int)$this->cfg['secondary_alphabet'];
        $p = (int)$this->cfg['primary_alphabet'];
        $n = (int)$this->cfg['dimension'];
        $minRoot = (int)$this->cfg['min_root'];
        $sMin = (int)$this->cfg['range_s_min'];
        $sMax = (int)$this->cfg['range_s_max'];

        if ($sMin > $sMax) {
            throw new InvalidArgumentException('range_s_min must be <= range_s_max.');
        }

        echo str_pad('s', 8) . str_pad('Lmax', 10) . "valid primary lengths\n";
        echo str_repeat('-', 108) . PHP_EOL;
        $rows = [];
        for ($s = $sMin; $s <= $sMax; ++$s) {
            $Lmax = Fabric::maxPrimaryLength($h, $s, $p);
            $valid = Fabric::validLengthsUpTo($Lmax, $n, $minRoot);
            echo str_pad((string)$s, 8) . str_pad((string)$Lmax, 10) . $this->formatValidList($valid) . PHP_EOL;
            $rows[] = ['s' => $s, 'Lmax' => $Lmax, 'valid' => $valid];
        }

        $this->last = [
            'type' => 'fabric_traverse',
            'rows' => $rows,
            'config' => $this->cfg,
        ];
    }

    private function witnessCommand(array $parts): void
    {
        if (!isset($parts[0])) {
            throw new InvalidArgumentException('Usage: witness <L>');
        }
        $L = max(1, (int)$parts[0]);
        $h = (int)$this->cfg['secondary_alphabet'];
        $p = (int)$this->cfg['primary_alphabet'];
        $n = (int)$this->cfg['dimension'];
        $minRoot = (int)$this->cfg['min_root'];
        $valid = MathUtil::validLengthInfo($L, $n, $minRoot);
        $s = Fabric::minSecondaryLengthForPrimaryLength($h, $p, $L);

        echo 'target primary length   : ' . $L . PHP_EOL;
        echo 'dimension-valid         : ' . ($valid['valid'] ? 'true' : 'false') . PHP_EOL;
        echo 'root m                  : ' . ($valid['m'] === null ? 'n/a' : (string)$valid['m']) . PHP_EOL;
        echo 'minimal secondary s     : ' . $s . PHP_EOL;
        echo 'condition               : h^s > p^(L-1)' . PHP_EOL;

        $this->last = [
            'type' => 'witness',
            'L' => $L,
            'valid' => $valid,
            'minimal_secondary_length' => $s,
            'config' => $this->cfg,
        ];
    }

    private function pasteCommand(array $parts): void
    {
        $limit = isset($parts[0]) ? (int)$parts[0] : (int)$this->cfg['match_limit'];
        $limit = max(1, min(12, $limit));

        echo "Paste multiline text. End with a line containing only .end\n";
        echo "Enter .cancel on its own line to abort.\n";

        $lines = [];
        while (true) {
            $line = $this->prompt('... ');
            if ($line === null) {
                echo PHP_EOL;
                return;
            }
            if ($line === '.cancel') {
                echo "Paste cancelled.\n";
                return;
            }
            if ($line === '.end') {
                break;
            }
            $lines[] = $line;
        }

        $text = implode("\n", $lines);
        $analysis = TextAnalyzer::analyze($text);
        $matches = MatchEngine::rank($this->cfg, $analysis, $limit);
        $this->lastMatches = $matches;

        echo 'pasted text lines      : ' . $analysis['line_count'] . PHP_EOL;
        echo 'pasted char length     : ' . $analysis['char_length'] . PHP_EOL;
        echo 'observed unique chars  : ' . $analysis['unique_count'] . PHP_EOL;
        echo 'effective sec alphabet : ' . max(2, $analysis['unique_count']) . PHP_EOL;
        echo 'active dimension       : ' . $this->cfg['dimension'] . PHP_EOL;
        echo 'unique char preview    : ' . $analysis['preview'] . PHP_EOL;
        echo str_repeat('-', 108) . PHP_EOL;
        echo str_pad('#', 4)
            . str_pad('p', 8)
            . str_pad('h', 8)
            . str_pad('s', 12)
            . str_pad('n', 6)
            . str_pad('Lmax', 10)
            . str_pad('closest_L', 12)
            . str_pad('m', 8)
            . str_pad('gap', 8)
            . str_pad('exact', 8)
            . "type\n";
        echo str_repeat('-', 108) . PHP_EOL;

        foreach ($matches as $i => $row) {
            echo str_pad((string)($i + 1), 4)
                . str_pad((string)$row['p'], 8)
                . str_pad((string)$row['h'], 8)
                . str_pad((string)$row['s'], 12)
                . str_pad((string)$row['n'], 6)
                . str_pad((string)$row['Lmax'], 10)
                . str_pad((string)$row['closest_L'], 12)
                . str_pad((string)$row['m'], 8)
                . str_pad((string)$row['gap'], 8)
                . str_pad($row['exact'] ? 'true' : 'false', 8)
                . $row['base_type']
                . PHP_EOL;
        }
        echo str_repeat('-', 108) . PHP_EOL;
        echo "Use 'match apply <rank>' to load one of these configs into the active session.\n";

        $this->last = [
            'type' => 'paste_match',
            'analysis' => [
                'line_count' => $analysis['line_count'],
                'char_length' => $analysis['char_length'],
                'unique_count' => $analysis['unique_count'],
                'unique_chars' => $analysis['unique_chars'],
                'preview' => $analysis['preview'],
            ],
            'matches' => $matches,
            'config' => $this->cfg,
        ];
    }

    private function matchCommand(array $parts): void
    {
        $sub = strtolower((string)($parts[0] ?? ''));
        if ($sub !== 'apply' || !isset($parts[1])) {
            throw new InvalidArgumentException('Usage: match apply <rank>');
        }
        if ($this->lastMatches === []) {
            throw new RuntimeException('No ranked matches available yet. Run paste first.');
        }
        $rank = (int)$parts[1];
        if ($rank < 1 || $rank > count($this->lastMatches)) {
            throw new InvalidArgumentException('Rank out of range.');
        }
        $row = $this->lastMatches[$rank - 1];
        $this->cfg['primary_alphabet'] = (int)$row['p'];
        $this->cfg['secondary_alphabet'] = (int)$row['h'];
        $this->cfg['secondary_length'] = (int)$row['s'];
        $this->cfg['dimension'] = (int)$row['n'];
        $this->validateConfig();
        echo 'Applied match #' . $rank . ' -> p=' . $row['p'] . ', h=' . $row['h'] . ', s=' . $row['s'] . ', n=' . $row['n'] . PHP_EOL;
    }

    private function saveCommand(array $parts): void
    {
        $file = (string)($parts[0] ?? 'ndcodex_config.json');
        file_put_contents($file, json_encode($this->cfg, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES));
        echo 'Saved config to ' . $file . PHP_EOL;
    }

    private function loadCommand(array $parts): void
    {
        $file = (string)($parts[0] ?? 'ndcodex_config.json');
        if (!is_file($file)) {
            throw new RuntimeException('Config file not found: ' . $file);
        }
        $data = json_decode((string)file_get_contents($file), true, 512, JSON_THROW_ON_ERROR);
        if (!is_array($data)) {
            throw new RuntimeException('Invalid config payload.');
        }
        foreach ($data as $k => $v) {
            if (array_key_exists($k, $this->cfg)) {
                $this->cfg[$k] = $v;
            }
        }
        $this->validateConfig();
        echo 'Loaded config from ' . $file . PHP_EOL;
    }

    private function exportCommand(array $parts): void
    {
        if ($this->last === []) {
            throw new RuntimeException('Nothing to export yet.');
        }
        $file = (string)($parts[0] ?? 'ndcodex_export.json');
        file_put_contents($file, json_encode($this->last, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES));
        echo 'Exported last result to ' . $file . PHP_EOL;
    }

    private function validateConfig(): void
    {
        foreach (['primary_alphabet', 'secondary_alphabet', 'secondary_length', 'dimension', 'min_root', 'range_s_min', 'range_s_max', 'match_limit', 'match_primary_min', 'match_primary_max', 'match_h_radius'] as $key) {
            $this->cfg[$key] = (int)$this->cfg[$key];
        }
        if ($this->cfg['primary_alphabet'] < 2 || $this->cfg['secondary_alphabet'] < 2) {
            throw new InvalidArgumentException('Alphabet lengths must be >= 2.');
        }
        if ($this->cfg['secondary_length'] < 1 || $this->cfg['dimension'] < 1 || $this->cfg['min_root'] < 1) {
            throw new InvalidArgumentException('secondary_length, dimension, and min_root must be >= 1.');
        }
        if ($this->cfg['range_s_min'] < 1 || $this->cfg['range_s_max'] < 1) {
            throw new InvalidArgumentException('Traversal bounds must be >= 1.');
        }
        if ($this->cfg['match_limit'] < 1 || $this->cfg['match_limit'] > 12) {
            throw new InvalidArgumentException('match_limit must be between 1 and 12.');
        }
        if ($this->cfg['match_primary_min'] < 2 || $this->cfg['match_primary_max'] < $this->cfg['match_primary_min']) {
            throw new InvalidArgumentException('Invalid match_primary_min/max bounds.');
        }
        if ($this->cfg['match_h_radius'] < 0) {
            throw new InvalidArgumentException('match_h_radius must be >= 0.');
        }
    }

    private function coerceValue(mixed $current, string $raw): mixed
    {
        if (is_int($current)) {
            if (!preg_match('/^-?\d+$/', trim($raw))) {
                throw new InvalidArgumentException('Expected integer value.');
            }
            return (int)$raw;
        }
        if (is_bool($current)) {
            $x = strtolower(trim($raw));
            if (in_array($x, ['1', 'true', 'yes', 'on'], true)) {
                return true;
            }
            if (in_array($x, ['0', 'false', 'no', 'off'], true)) {
                return false;
            }
            throw new InvalidArgumentException('Expected boolean value.');
        }
        return $raw;
    }

    /** @param list<array{L:int,m:int}> $valid */
    private function formatValidList(array $valid): string
    {
        if ($valid === []) {
            return '(none)';
        }
        $parts = [];
        foreach ($valid as $row) {
            $parts[] = $row['L'] . '(m=' . $row['m'] . ')';
            if (count($parts) >= 18) {
                $parts[] = '...';
                break;
            }
        }
        return implode(', ', $parts);
    }

    private function prompt(string $text): ?string
    {
        if (function_exists('readline')) {
            $line = readline($text);
            if ($line === false) {
                return null;
            }
            if ($text === 'nDCodex> ' && trim($line) !== '') {
                readline_add_history($line);
            }
            return $line;
        }
        echo $text;
        $line = fgets(STDIN);
        return $line === false ? null : rtrim($line, "\r\n");
    }
}

$repl = new NDCodex();
$repl->run();
