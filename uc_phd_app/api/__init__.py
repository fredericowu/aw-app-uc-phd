"""Domain-split routers.

``projects.py`` is the v1 surface. The publications/researchers graph from the
sibling plan lands as ``people.py`` / ``publications.py`` / ``graph.py``
alongside it — new tables in the same SQLite file, new routers mounted in
``routes.py``, nothing here rewritten.
"""
