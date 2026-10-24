"""The controlled evaluation: does human-found data teach the verifier more
than LLM-generated data?

    data.py     splits by headline, exploit / true / fresh / synthetic / VitaminC sets
    metrics.py  refute recall, false-positive rate, VitaminC macro-F1, by edit type,
                all with 95% bootstrap confidence intervals
    run.py      trains v1-human, v1-synthetic, v1-combined with identical settings
                and counts, scores them and v0 on every test set, saves results

    python -m evaluation.run
"""
