Treat me like a stateful math REPL in chat.

`p` = primary alphabet, `h` = secondary alphabet, `s` = secondary length, and `n` = dimension. I use two exact rules: `L` is valid iff `L = m^n` with `m >= min_root`, and the fabric constraint is `h^s > p^(L-1)`. Any config change you make stays active for the rest of this conversation until you `reset`. Right now the default state is `p=7, h=10, s=5, n=2, min_root=2`; in that state, `p` is prime, `Lmax = 6`, and the valid primary length at `s=5` is `4`.  

The easiest ways to work with me are:

**Inspect the current state**

```text
show
help
explain lengths
classify
```

**Change the model and recompute**

```text
set dimension 3
set primary_alphabet 11
set secondary_alphabet 16
set secondary_length 8
lengths
lengths 12
witness 16
fabric traverse
```

**Paste text or code for matching**
Just paste the block directly in chat. I treat it like the `paste` pipeline: I count Unicode characters, count unique characters, use `char_length` as `s`, and rank candidate configs near the observed unique-character count. After that you can say:

```text
match refine 1
match apply 1
```

In chat, you do **not** need `.end`; the whole pasted block is the payload.  

**Move state in and out**

```text
save
export
load
reset
```

In chat, `save` and `export` return JSON instead of writing files, and `load` expects you to paste JSON content for me to apply and validate. 

You can also speak naturally instead of using commands. For example:

* “What are the valid primary lengths if `s = 8`?”
* “Is `L = 16` dimension-valid, and what minimal `s` realizes it?”
* “Analyze this code block and find the best matching config.”

A good first move is:

```text
show
```

Or paste a block of text/code and I’ll analyze it.
