"""可编辑的受约束流程图；先编译检查，再交给执行器运行。"""

import json
import re
import threading
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .artifacts import write_json

Kind = Literal[
    "start", "coder", "validate", "reviewer", "verifier", "fixer", "custom", "gate", "end"
]
INPUTS = {"task", "code", "validation", "review", "verification", "upstream"}
TITLES = {
    "start": "开始",
    "coder": "编码",
    "validate": "执行验收",
    "reviewer": "发现问题",
    "verifier": "验证问题",
    "fixer": "修复",
    "custom": "自定义角色",
    "gate": "结果判定",
    "end": "完成",
}


class Node(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,39}$")
    kind: Kind
    name: str = Field(min_length=1, max_length=60)
    prompt: str = Field(default="", max_length=6000)
    inputs: list[Literal["task", "code", "validation", "review", "verification", "upstream"]] = (
        Field(default_factory=lambda: ["task", "upstream"], max_length=6)
    )
    x: float = Field(default=40, ge=0, le=4000)
    y: float = Field(default=40, ge=0, le=3000)


class Edge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    target: str
    condition: Literal["always", "pass", "repair"] = "always"


class Graph(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    name: str = Field(min_length=1, max_length=80)
    nodes: list[Node] = Field(min_length=7, max_length=24)
    edges: list[Edge] = Field(min_length=7, max_length=32)
    max_steps: int = Field(default=160, ge=10, le=300, strict=True)


def parse_graph(data: dict) -> Graph:
    try:
        graph = Graph.model_validate(data)
    except ValidationError as exc:
        raise ValueError("流程配置格式无效：检查节点类型、标识、长度、位置和步数上限") from exc
    compile_graph(graph)
    return graph


def compile_graph(graph: Graph) -> dict[str, Node]:
    """允许自定义分析节点插入各条边，只允许判定节点发起有上限的修复回路。"""
    nodes = {node.id: node for node in graph.nodes}
    if len(nodes) != len(graph.nodes):
        raise ValueError("节点标识不能重复")
    by_kind = {kind: [n for n in graph.nodes if n.kind == kind] for kind in TITLES}
    for kind in ("start", "coder", "validate", "reviewer", "fixer", "gate", "end"):
        if len(by_kind[kind]) != 1:
            raise ValueError(f"流程必须恰好包含一个「{TITLES[kind]}」节点")
    if len(by_kind["verifier"]) > 1:
        raise ValueError("第一版最多支持一个验证者节点")
    for node in graph.nodes:
        if not node.name.strip() or (node.kind == "custom" and not node.prompt.strip()):
            raise ValueError(f"「{node.name}」需要有效名称，自定义角色还需要填写职责提示词")
        if len(set(node.inputs)) != len(node.inputs):
            raise ValueError(f"「{node.name}」的读取信息不能重复")
        if node.kind == "custom" and "upstream" not in node.inputs:
            raise ValueError("自定义角色必须读取上游输出，以保留连线的数据传递")
    outgoing: dict[str, list[Edge]] = {key: [] for key in nodes}
    seen = set()
    for edge in graph.edges:
        if edge.source not in nodes or edge.target not in nodes:
            raise ValueError("连线引用了不存在的节点")
        signature = (edge.source, edge.target, edge.condition)
        if signature in seen or edge.source == edge.target:
            raise ValueError("不能重复连线或连接节点自身")
        seen.add(signature)
        outgoing[edge.source].append(edge)
    for node in graph.nodes:
        expected = (
            {"pass", "repair"}
            if node.kind == "gate"
            else set()
            if node.kind == "end"
            else {"always"}
        )
        if (
            len(outgoing[node.id]) != len(expected)
            or {e.condition for e in outgoing[node.id]} != expected
        ):
            raise ValueError(
                f"「{node.name}」的出口无效：普通节点一个出口，判定节点需要通过与修复两个出口，完成节点无出口"
            )
    start, gate, end, validate = (by_kind[k][0].id for k in ("start", "gate", "end", "validate"))
    if any(e.target == start for e in graph.edges):
        raise ValueError("开始节点不能有入口")

    def walk(begin: str, stop: str) -> list[str]:
        path = []
        while begin != stop:
            if begin in path or nodes[begin].kind in {"gate", "end"}:
                raise ValueError("存在不受控的循环或无法到达指定出口；只能通过判定节点回到验收")
            path.append(begin)
            begin = outgoing[begin][0].target
        return path

    main = walk(start, gate)
    passed = walk(next(e.target for e in outgoing[gate] if e.condition == "pass"), end)
    repair = walk(next(e.target for e in outgoing[gate] if e.condition == "repair"), validate)
    required = ["start", "coder", "validate", "reviewer"] + (
        ["verifier"] if by_kind["verifier"] else []
    )
    if [nodes[key].kind for key in main if nodes[key].kind != "custom"] != required:
        raise ValueError(
            "主路径必须依次经过：开始 → 编码 → 验收 → 发现问题 → 可选验证者 → 判定；"
            "中间可插入自定义角色"
        )
    if any(nodes[key].kind != "custom" for key in passed):
        raise ValueError("通过路径只能经过自定义角色后到达完成，不能再次修改代码或审查结果")
    if [nodes[key].kind for key in repair if nodes[key].kind != "custom"] != ["fixer"]:
        raise ValueError("修复路径必须经过一个修复节点，再回到验收；中间可插入自定义角色")
    if set(main + passed + repair + [gate, end]) != set(nodes):
        raise ValueError("存在未接入有效路径的节点，请连线或删除")
    # 自定义节点读取不存在的数据时在运行前阻止，而不是把缺失内容交给模型猜测。
    available = {"task", "upstream"}
    produces = {
        "coder": "code",
        "validate": "validation",
        "reviewer": "review",
        "verifier": "verification",
    }
    for key in main + [gate] + passed:
        node = nodes[key]
        if node.kind == "custom" and not set(node.inputs) <= available:
            missing = ", ".join(sorted(set(node.inputs) - available))
            raise ValueError(f"「{node.name}」读取了尚未产生的信息：{missing}")
        if node.kind in produces:
            available.add(produces[node.kind])
    for key in repair:
        node = nodes[key]
        if node.kind == "custom" and not set(node.inputs) <= available:
            raise ValueError(f"「{node.name}」读取了尚未产生的信息")
        if node.kind == "fixer":
            available -= {"validation", "review", "verification"}
    return nodes


def default_graph(verified: bool = False) -> Graph:
    kinds = (
        ["start", "coder", "validate", "reviewer"]
        + (["verifier"] if verified else [])
        + ["gate", "end"]
    )
    nodes = [
        Node(id=k, kind=k, name=TITLES[k], x=50 + i % 4 * 250, y=60 + i // 4 * 190)
        for i, k in enumerate(kinds)
    ]
    nodes.append(Node(id="fixer", kind="fixer", name=TITLES["fixer"], x=550, y=460))
    edges = [
        Edge(source=a, target=b) for a, b in zip(kinds, kinds[1:], strict=False) if a != "gate"
    ]
    edges += [
        Edge(source="gate", target="end", condition="pass"),
        Edge(source="gate", target="fixer", condition="repair"),
        Edge(source="fixer", target="validate"),
    ]
    return Graph(name="四角色交叉验证" if verified else "三角色代码审查", nodes=nodes, edges=edges)


class GraphLibrary:
    """本机流程库；运行时持有独立快照，保存画布不会改动正在执行的任务。"""

    def __init__(self, directory: Path):
        self.directory = directory
        self.lock = threading.RLock()

    def list(self) -> list[dict]:
        with self.lock:
            items = []
            for path in sorted(self.directory.glob("*.json")):
                try:
                    definition = parse_graph(json.loads(path.read_text(encoding="utf-8")))
                    items.append({"id": path.stem, "definition": definition.model_dump()})
                except (OSError, ValueError, TypeError):
                    continue
            return items

    def save(self, data: dict, identifier: str | None = None) -> dict:
        definition = parse_graph(data)
        if identifier is not None and not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise ValueError("流程编号无效")
        identifier = identifier or uuid4().hex
        with self.lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            write_json(self.directory / f"{identifier}.json", definition.model_dump())
        return {"id": identifier, "definition": definition.model_dump()}
