# pip install graphviz
from graphviz import Digraph
from collections.abc import Mapping, Sequence
import re
import itertools

class GraphMeNode:
    """Marker base class. Subclass me to be included in the graph."""
    pass

def _iter_targets(value):
    """Yield (target_node, via_label) pairs from attribute value."""
    from collections.abc import Mapping, Sequence
    if isinstance(value, GraphMeNode):
        yield value, None
    elif isinstance(value, Mapping):
        for k, v in value.items():
            if isinstance(v, GraphMeNode):
                yield v, f"[{repr(k)}]"
    elif isinstance(value, (set, frozenset, tuple, list)):
        for i, v in enumerate(value):
            if isinstance(v, GraphMeNode):
                yield v, f"[{i}]"
    # else: ignore

def _short_id(obj):
    return hex(id(obj))[-6:]

def _best_label(obj):
    base = f"{obj.__class__.__name__}#{_short_id(obj)}"
    for attr in ("name", "title", "id", "slug"):
        if hasattr(obj, attr):
            try:
                val = getattr(obj, attr)
                if isinstance(val, (str, int)):
                    return f"{base}\\n{attr}={val}"
            except Exception:
                pass
    return base

def _palette():
    # pleasant distinct-ish colors for Graphviz (can extend)
    return [
        "red", "blue", "green", "orange", "purple", "brown", "teal",
        "gold", "gray40", "magenta", "darkgreen", "navy", "chocolate",
        "deeppink", "darkorange", "darkturquoise", "indigo", "crimson",
    ]

def _color_for_key(key, cache, colors):
    if key not in cache:
        cache[key] = colors[len(cache) % len(colors)]
    return cache[key]

def graph_me(
    roots,
    filename="graph_me",
    format="svg",
    include_private=True,
    follow_slots=True,
    max_nodes=500,
):
    """
    Build and render a graph starting from one or more GraphMeNode roots.
    Edges are color-coded by the attribute name that links nodes.
    """
    if isinstance(roots, GraphMeNode):
        roots = [roots]
    roots = list(roots)

    dot = Digraph("graph_me", node_attr=dict(shape="box", fontsize="10"))
    seen = set()
    queue = list(roots)
    edge_color_cache = {}
    colors = _palette()
    ncount = 0

    def add_node(n):
        nid = str(id(n))
        if nid in seen:
            return False
        seen.add(nid)
        dot.node(nid, _best_label(n))
        return True

    for r in roots:
        add_node(r)

    while queue:
        node = queue.pop(0)
        nid = str(id(node))
        if ncount > max_nodes:
            dot.node("TRUNC", "…truncated…", shape="note", style="dashed")
            dot.edge(nid, "TRUNC", style="dashed")
            break
        ncount += 1

        # Gather attributes to follow
        attrs = {}
        # __dict__
        if hasattr(node, "__dict__"):
            attrs.update(node.__dict__)

        # __slots__ (optional)
        if follow_slots and hasattr(node, "__slots__"):
            for s in node.__slots__:
                if isinstance(s, str) and hasattr(node, s):
                    attrs[s] = getattr(node, s)

        for attr_name, value in attrs.items():
            # Skip dunder
            if attr_name.startswith("__") and attr_name.endswith("__"):
                continue
            # Respect private choice
            if not include_private and attr_name.startswith("_"):
                continue

            # Find GraphMeNode targets inside the value
            for tgt, idx_label in _iter_targets(value):
                tid = str(id(tgt))
                if tid not in seen:
                    add_node(tgt)
                    queue.append(tgt)

                # Color by the *attribute name* (not the collection index)
                color = _color_for_key(attr_name, edge_color_cache, colors)
                # Build a readable edge label
                edge_label = attr_name if idx_label is None else f"{attr_name}{idx_label}"
                dot.edge(nid, tid, label=edge_label, color=color, fontcolor=color)

    # Render
    dot.render(filename=filename, format=format, cleanup=True)
    return f"{filename}.{format}", dot

# DEMO

class Author(GraphMeNode):
    def __init__(self, name):
        self.name = name
        self._books = []         # private attribute => will be colored uniquely

class Book(GraphMeNode):
    def __init__(self, title):
        self.title = title
        self.chapters = []

class Chapter(GraphMeNode):
    def __init__(self, title, notes=None):
        self.title = title
        self.notes = notes or []

def demo_func():
    a = Author("Ada")
    b1 = Book("Apples: A Thesis")
    b2 = Book("Bananas: A Rebuttal")
    a._books.extend([b1, b2])

    c1 = Chapter("Claim: Apples are popular")
    c2 = Chapter("Evidence: survey results")
    b1.chapters.extend([c1, c2])

    outfile, _ = graph_me(a, filename="idea_graph", format="svg", include_private=True)
    print("wrote", outfile)

if __name__ == "__main__":
    demo_func()
