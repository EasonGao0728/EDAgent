from __future__ import annotations

import ast
import hashlib

from .common import require_text


CODE_SCHEMA = {"type": "object", "additionalProperties": False,
               "properties": {"description": {"type": "string", "maxLength": 800},
                              "source": {"type": "string", "minLength": 90,
                                  "description": "Complete executable Python SOURCE CODE. Start with the exact function signature and include its indented implementation. This is not an API name.",
                                  "pattern": "^def propose_moves\\(context, budget, rng\\):[\\s\\S]*$"}},
               "required": ["description", "source"]}

OPERATOR_API = """You are a Python PROGRAMMER. Write real executable Python code in the source field.
Start source with: def propose_moves(context, budget, rng):
Put imports inside this function if needed. Implement the function body, not prose.
context.summary() -> {core:{x,y,width,height},grid,min_spacing,...}
context.macros(ids=None) -> list of {id,x,y,width,height,fixed,orientation,allowed_orientations}
context.ports() -> list of {id,x,y}
context.nets(ids=None) -> LIST of {id,nodes:list[str],weight}; node ids are macros or ports.
Iterate `for net in context.nets():` and read `net['nodes']`.
Never index the nets list by a string net id. For an id lookup, first build a dict.
context.is_legal(moves) -> bool for a COMPLETE joint final state.
context.hpwl(moves) -> weighted HPWL; raises ValueError for invalid moves.
These are METHODS, not attributes. There is NO context.core(), context.grid,
context.min_spacing or context.movable_ids. Read those from context.summary().
rng is random.Random. budget['max_candidates'] is the output count limit.
budget['target_macro_ids'] is the EXACT allowed scope. Iterate those ids, not all movable_ids.
RETURN a list of batches: [{'moves':[{'macro_id':'a','x':10,'y':20}]}].
Coordinates are lower-left corners, not centers. Align to grid. Keep within core,
avoid fixed macros, blockages, overlap and min_spacing. Orientation may be omitted.
Use loops to construct/search candidates from actual geometry and connectivity.
Use context.is_legal BEFORE context.hpwl. A useful approach is a bounded grid or
neighborhood search, testing candidate moves relative to net neighbors.
The argument to is_legal and hpwl is a LIST OF MOVES, not {'moves':...}.
For example: moves=[{'macro_id':m['id'],'x':nx,'y':ny}];
if context.is_legal(moves): score=context.hpwl(moves).
Wrap it as {'moves':moves} ONLY when appending to the returned results list.
Correct output: [{'moves':[{'macro_id':'a','x':10,'y':20}]}].
Incorrect output: [[{'macro_id':'a','x':10,'y':20}]].
Do not reimplement overlap or spacing checks; use context.is_legal.
Only move target_macro_ids from the ToolRequest. Code must use the real context;
do not hardcode a precomputed final placement. Include fallback when no legal move.
Allowed imports: math, random, itertools, statistics, collections. No files, network,
processes or extra dependencies. Do not modify the evaluator or constraints.
Use a single compact function, preferably 30-60 lines. Keep runtime below 5 seconds: fewer than 1500 trials.
Return at most max_candidates distinct candidate batches, preferably ranked.
If feedback contains an error, fix its specific cause; if no improvement, change
the search logic based on evidence. Brief description is a public mechanism summary.
"""


def check_code(result):
    require_text(result.get("description"), "operator description")
    source = require_text(result.get("source"), "operator source", 24000)
    tree = ast.parse(source)
    if not any(isinstance(n, ast.FunctionDef) and n.name == "propose_moves" for n in tree.body):
        raise ValueError("expected top-level function propose_moves")
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "context":
            if node.attr not in {"summary", "macros", "ports", "nets", "region", "hpwl", "is_legal"}:
                raise ValueError(f"unsupported context.{node.attr}: use context.summary() for core/grid/min_spacing/movable_ids; available methods are summary,macros,ports,nets,region,hpwl,is_legal")
    return source, hashlib.sha256(source.encode("utf-8")).hexdigest()
