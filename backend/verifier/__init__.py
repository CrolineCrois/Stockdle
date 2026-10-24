"""The evidence verifier: decides every round on submit.

    retrieval.py   BM25 over the passage corpus (top-k, optionally excluding
                   the source article for breaking-news mode)
    model.py       a 3-way fact-verification model: SUPPORTED / REFUTED / NEI
    verify.py      claim -> passages -> verdict, with the passages it used
    registry.py    verifier versions on disk, which one is live

The style model in ``detector/`` keeps driving the live meter as a "first
glance" signal; it never decides an outcome.
"""
