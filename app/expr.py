"""규칙 표현식 평가 — docs/04-architecture.md §4.

`expr` 은 **제한된 표현식만** 평가한다. `eval()` 을 쓰지 않고 파이썬 AST 를 직접
훑으면서 허용한 노드만 계산한다. 규칙 파일은 담당자가 직접 고치는 것을 전제로 하므로,
YAML 한 줄이 임의 코드 실행으로 이어지면 안 된다.

YAML 의 표현식에는 파이썬이 아닌 표기가 섞여 있다. 평가 전에 전처리한다.

    worklog.rows[].hours          →  pluck(worklog.rows, "hours")
    a contains b                  →  contains(a, b)
    a within b                    →  within(a, b)
    true / false / null           →  True / False / None
"""
from __future__ import annotations

import ast
import re
from datetime import date, datetime, time, timedelta
from typing import Any, Callable

from . import normalize as nz
from .models import MISSING, Namespace, Period, format_value


class ExprError(Exception):
    """표현식을 평가할 수 없다."""


class MissingValueError(ExprError):
    """필요한 값이 추출되지 않았다 → 🔵 판독 불가로 올린다."""

    def __init__(self, name: str = ""):
        super().__init__(f"값이 추출되지 않았습니다: {name}" if name else "값이 추출되지 않았습니다")
        self.name = name


# ------------------------------------------------------------------ 전처리

_PLUCK_RE = re.compile(r"([A-Za-z_][\w.]*)\[\]\.([A-Za-z_]\w*)")
_INFIX_RE = {
    "contains": re.compile(r"^(?P<left>.+?)\s+contains\s+(?P<right>.+)$"),
    "within": re.compile(r"^(?P<left>.+?)\s+within\s+(?P<right>.+)$"),
}


def preprocess(source: str) -> str:
    """YAML 의 의사 문법을 파이썬 표현식으로 바꾼다."""
    text = source.strip()
    text = _PLUCK_RE.sub(lambda m: f'pluck({m.group(1)}, "{m.group(2)}")', text)
    for name, pattern in _INFIX_RE.items():
        match = pattern.match(text)
        if match:
            text = f"{name}({match.group('left').strip()}, {match.group('right').strip()})"
    return text


# ------------------------------------------------------------ 내장 함수들

def _unwrap(value: Any) -> Any:
    if value is MISSING:
        raise MissingValueError()
    return value


def _fn_pluck(sequence: Any, key: str) -> list[Any]:
    """`rows[].hours` — 각 행에서 키 하나씩 뽑아 목록으로."""
    if sequence is MISSING or sequence is None:
        raise MissingValueError(f"[].{key}")
    out = []
    for item in sequence:
        value = safe_getattr(item, key)
        if value is not MISSING:
            out.append(value)
    return out


def _to_minutes(value: Any) -> int | None:
    if isinstance(value, datetime):
        return value.hour * 60 + value.minute
    if isinstance(value, time):
        return value.hour * 60 + value.minute
    parsed = nz.parse_time(value)
    if parsed is None:
        return None
    return parsed[0] * 60 + parsed[1]


def _fn_hours_between(start: Any, end: Any) -> float:
    """`09:00`~`14:00` → 5.0. 자정을 넘기면 다음 날로 본다."""
    lo, hi = _to_minutes(_unwrap(start)), _to_minutes(_unwrap(end))
    if lo is None or hi is None:
        raise ExprError("시각을 해석할 수 없습니다")
    if hi < lo:
        hi += 24 * 60
    return round((hi - lo) / 60, 2)


def _fn_dates_in(period: Any) -> list[date]:
    period = _unwrap(period)
    if isinstance(period, Period):
        return period.dates()
    raise ExprError("기간이 아닙니다")


def _fn_days_in(period: Any) -> int:
    return len(_fn_dates_in(period))


def _fn_is_holiday(value: Any) -> bool:
    """주말 판정. 법정공휴일 표는 아직 없다 — 지침 확정 후 붙인다(R-SCH-020)."""
    day = nz.parse_date(_unwrap(value))
    if day is None:
        raise ExprError("날짜를 해석할 수 없습니다")
    return day.weekday() >= 5


def _fn_match(value: Any, pattern: Any) -> bool:
    text = _unwrap(value)
    if text is None:
        return False
    try:
        return re.search(str(pattern), str(text)) is not None
    except re.error as exc:
        raise ExprError(f"정규식 오류: {exc}") from exc


def _fn_all_equal(*values: Any) -> bool:
    normalized = []
    for value in values:
        value = _unwrap(value)
        normalized.append(nz.strip_spaces(value) if isinstance(value, str) else value)
    return all(v == normalized[0] for v in normalized[1:]) if normalized else True


def _fn_contains(haystack: Any, needle: Any) -> bool:
    haystack, needle = _unwrap(haystack), _unwrap(needle)
    if haystack is None or needle is None:
        return False
    if isinstance(haystack, str) or isinstance(needle, str):
        return (nz.strip_spaces(needle) or "") in (nz.strip_spaces(haystack) or "")
    return needle in haystack


def _fn_within(inner: Any, outer: Any) -> bool:
    """기간 a 가 기간 b 안에 들어가는가 (R-SCH-015)."""
    inner, outer = _unwrap(inner), _unwrap(outer)
    if not isinstance(inner, Period) or not isinstance(outer, Period):
        return False
    if inner.start_date is None or inner.end_date is None:
        return False
    return inner.start in outer and inner.end in outer


def _fn_normalize(value: Any) -> Any:
    value = _unwrap(value)
    return nz.strip_spaces(value) if value is not None else None


def _fn_digits(value: Any) -> Any:
    return nz.digits_only(_unwrap(value))


def _guarded(func: Callable[..., Any]) -> Callable[..., Any]:
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return func(*(_unwrap(a) for a in args), **kwargs)
    return wrapper


def _fn_len(value: Any) -> int:
    value = _unwrap(value)
    return 0 if value is None else len(value)


def _fn_sum(values: Any) -> Any:
    values = _unwrap(values)
    clean = [v for v in values if v is not None and v is not MISSING]
    if not clean:
        return 0
    total = sum(clean)
    return round(total, 6) if isinstance(total, float) else total


FUNCTIONS: dict[str, Callable[..., Any]] = {
    # 파이썬 내장 중 안전한 것만
    "len": _fn_len,
    "sum": _fn_sum,
    "abs": _guarded(abs),
    "max": _guarded(max),
    "min": _guarded(min),
    "round": _guarded(round),
    "int": _guarded(int),
    "float": _guarded(float),
    "str": _guarded(str),
    "bool": _guarded(bool),
    "set": _guarded(lambda v: set(v or ())),
    "list": _guarded(lambda v: list(v or ())),
    "sorted": _guarded(lambda v: sorted(v or ())),
    "any": _guarded(any),
    "all": _guarded(all),
    # 도메인 함수 (docs/03 §1 정규화 함수)
    "normalize": _fn_normalize,
    "digits": _fn_digits,
    "money": _guarded(nz.money),
    "hours": _guarded(nz.parse_hours),
    "hangul_amount": _guarded(nz.hangul_amount),
    "region_of": _guarded(nz.region_of),
    "regions_of": _guarded(nz.regions_of),
    "similarity": _guarded(nz.similarity),
    "hours_between": _fn_hours_between,
    "dates_in": _fn_dates_in,
    "days_in": _fn_days_in,
    "is_holiday": _fn_is_holiday,
    "match": _fn_match,
    "all_equal": _fn_all_equal,
    "contains": _fn_contains,
    "within": _fn_within,
    "pluck": _fn_pluck,
}

CONSTANTS: dict[str, Any] = {
    "true": True,
    "false": False,
    "null": None,
    "None": None,
    "True": True,
    "False": False,
}


# --------------------------------------------------------------- 속성 접근

#: 날짜·시간 객체에서 읽어도 되는 속성. 그 외 객체의 속성 접근은 막는다.
_TEMPORAL_ATTRS = {"year", "month", "day", "hour", "minute", "second", "days", "seconds"}


def safe_getattr(target: Any, name: str) -> Any:
    """화이트리스트 기반 속성 접근. 던더·비공개 이름은 차단한다."""
    if name.startswith("_"):
        raise ExprError(f"접근할 수 없는 속성입니다: {name}")
    if target is MISSING:
        raise MissingValueError(name)
    if target is None:
        return MISSING
    if isinstance(target, Namespace):
        return target[name]
    if isinstance(target, dict):
        return target.get(name, MISSING)
    if isinstance(target, Period):
        if name in ("start", "end", "start_date", "end_date", "days"):
            return getattr(target, name)
        if name == "dates":
            return target.dates()
        raise ExprError(f"기간에 없는 속성입니다: {name}")
    if isinstance(target, datetime):
        if name == "date":
            return target.date()
        if name == "time":
            return target.time()
        if name in _TEMPORAL_ATTRS:
            return getattr(target, name)
    elif isinstance(target, date):
        if name == "date":
            return target
        if name in _TEMPORAL_ATTRS:
            return getattr(target, name)
    elif isinstance(target, timedelta):
        if name in _TEMPORAL_ATTRS:
            return getattr(target, name)
    raise ExprError(f"'{type(target).__name__}' 의 속성 '{name}' 은 읽을 수 없습니다")


# ------------------------------------------------------------------ 평가기

_ALLOWED_NODES = (
    ast.Expression, ast.BoolOp, ast.BinOp, ast.UnaryOp, ast.Compare, ast.Call,
    ast.IfExp, ast.Attribute, ast.Subscript, ast.Name, ast.Constant, ast.Load,
    ast.List, ast.Tuple, ast.Set, ast.Dict, ast.GeneratorExp, ast.ListComp,
    ast.SetComp, ast.comprehension, ast.Slice, ast.Index if hasattr(ast, "Index") else ast.Slice,
    ast.And, ast.Or, ast.Not, ast.USub, ast.UAdd,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn,
    ast.Starred, ast.arguments, ast.arg,
)

_BINOPS: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a ** b,
}


def _compare(op: ast.cmpop, left: Any, right: Any) -> bool:
    if isinstance(op, ast.Eq):
        return _eq(left, right)
    if isinstance(op, ast.NotEq):
        return not _eq(left, right)
    if isinstance(op, ast.In):
        return _in(left, right)
    if isinstance(op, ast.NotIn):
        return not _in(left, right)
    if left is None or right is None:
        # 공란은 대소 비교의 대상이 되지 않는다 → 위반으로 본다.
        return False
    left, right = _align_temporal(left, right)
    if isinstance(op, ast.Lt):
        return left < right
    if isinstance(op, ast.LtE):
        return left <= right
    if isinstance(op, ast.Gt):
        return left > right
    if isinstance(op, ast.GtE):
        return left >= right
    raise ExprError(f"지원하지 않는 비교 연산자: {type(op).__name__}")


def _align_temporal(left: Any, right: Any) -> tuple[Any, Any]:
    """날짜와 일시를 섞어 비교할 때 날짜 기준으로 맞춘다.

    근로기간이 `2026.3.3 ~ 2026.3.31`(시각 없음)인데 근로일자가 date 라면,
    한쪽만 00:00 을 달고 있어 종료일 당일이 기간 밖으로 밀린다.
    """
    if isinstance(left, datetime) and isinstance(right, date) and not isinstance(right, datetime):
        return left.date(), right
    if isinstance(right, datetime) and isinstance(left, date) and not isinstance(left, datetime):
        return left, right.date()
    return left, right


def _eq(left: Any, right: Any) -> bool:
    """숫자는 오차를 허용하고, 문자열은 공백을 무시하고 비교한다.

    표 추출 과정에서 `15` 가 `15.0` 으로, `권석재` 가 `권 석 재` 로 나오는 일이 잦다.
    이걸 그대로 비교하면 정상 서류에서 오탐이 난다.
    """
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, bool) or isinstance(right, bool):
        return left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return abs(left - right) < 1e-6
    if isinstance(left, str) and isinstance(right, str):
        return nz.strip_spaces(left) == nz.strip_spaces(right)
    if isinstance(left, datetime) and isinstance(right, date) and not isinstance(right, datetime):
        return left.date() == right
    if isinstance(right, datetime) and isinstance(left, date) and not isinstance(left, datetime):
        return left == right.date()
    return left == right


def _in(needle: Any, haystack: Any) -> bool:
    if haystack is None or haystack is MISSING:
        return False
    if isinstance(haystack, (Period, Namespace)) or hasattr(haystack, "__contains__"):
        try:
            return needle in haystack
        except TypeError:
            return False
    return False


class _Evaluator(ast.NodeVisitor):
    def __init__(self, scope: dict[str, Any]):
        self.scope = scope

    # -- 진입점 ---------------------------------------------------------
    def run(self, tree: ast.Expression) -> Any:
        return self.visit(tree.body)

    def generic_visit(self, node: ast.AST) -> Any:
        raise ExprError(f"허용되지 않은 문법입니다: {type(node).__name__}")

    def visit(self, node: ast.AST) -> Any:
        if not isinstance(node, _ALLOWED_NODES):
            raise ExprError(f"허용되지 않은 문법입니다: {type(node).__name__}")
        return super().visit(node)

    # -- 리터럴 ---------------------------------------------------------
    def visit_Constant(self, node: ast.Constant) -> Any:
        return node.value

    def visit_List(self, node: ast.List) -> list:
        return [self.visit(item) for item in node.elts]

    def visit_Tuple(self, node: ast.Tuple) -> tuple:
        return tuple(self.visit(item) for item in node.elts)

    def visit_Set(self, node: ast.Set) -> set:
        return {self.visit(item) for item in node.elts}

    def visit_Dict(self, node: ast.Dict) -> dict:
        return {self.visit(k): self.visit(v) for k, v in zip(node.keys, node.values)}

    # -- 이름·속성 ------------------------------------------------------
    def visit_Name(self, node: ast.Name) -> Any:
        name = node.id
        if name in self.scope:
            return self.scope[name]
        if name in CONSTANTS:
            return CONSTANTS[name]
        if name in FUNCTIONS:
            return FUNCTIONS[name]
        raise MissingValueError(name)

    def visit_Attribute(self, node: ast.Attribute) -> Any:
        return safe_getattr(self.visit(node.value), node.attr)

    def visit_Subscript(self, node: ast.Subscript) -> Any:
        target = self.visit(node.value)
        key = self.visit(node.slice) if not isinstance(node.slice, ast.Slice) else None
        if target is MISSING or target is None:
            raise MissingValueError()
        if isinstance(target, (Namespace, dict)):
            value = target[key] if isinstance(target, Namespace) else target.get(key, MISSING)
            if value is MISSING:
                raise MissingValueError(str(key))
            return value
        try:
            return target[key]
        except (KeyError, IndexError, TypeError) as exc:
            raise ExprError(f"인덱스 접근 실패: {exc}") from exc

    # -- 연산 -----------------------------------------------------------
    def visit_BinOp(self, node: ast.BinOp) -> Any:
        left, right = self.visit(node.left), self.visit(node.right)
        if left is MISSING or right is MISSING:
            raise MissingValueError()
        handler = _BINOPS.get(type(node.op))
        if handler is None:
            raise ExprError(f"지원하지 않는 연산자: {type(node.op).__name__}")
        return handler(left, right)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:
        operand = self.visit(node.operand)
        if isinstance(node.op, ast.Not):
            return not operand
        if operand is MISSING:
            raise MissingValueError()
        if isinstance(node.op, ast.USub):
            return -operand
        return +operand

    def visit_BoolOp(self, node: ast.BoolOp) -> Any:
        if isinstance(node.op, ast.And):
            result: Any = True
            for value in node.values:
                result = self.visit(value)
                if not result:
                    return result
            return result
        result = False
        for value in node.values:
            result = self.visit(value)
            if result:
                return result
        return result

    def visit_Compare(self, node: ast.Compare) -> bool:
        left = self.visit(node.left)
        for op, comparator in zip(node.ops, node.comparators):
            right = self.visit(comparator)
            if left is MISSING or right is MISSING:
                raise MissingValueError()
            try:
                if not _compare(op, left, right):
                    return False
            except TypeError:
                # 공란(None)이 섞여 비교가 성립하지 않으면 '맞지 않다' 로 본다.
                return False
            left = right
        return True

    def visit_IfExp(self, node: ast.IfExp) -> Any:
        return self.visit(node.body) if self.visit(node.test) else self.visit(node.orelse)

    # -- 호출·내포 ------------------------------------------------------
    def visit_Call(self, node: ast.Call) -> Any:
        if not isinstance(node.func, ast.Name):
            raise ExprError("함수는 이름으로만 호출할 수 있습니다")
        func = FUNCTIONS.get(node.func.id)
        if func is None:
            raise ExprError(f"허용되지 않은 함수입니다: {node.func.id}")
        args = []
        for arg in node.args:
            if isinstance(arg, ast.Starred):
                args.extend(self.visit(arg.value))
            else:
                args.append(self.visit(arg))
        if node.keywords:
            raise ExprError("키워드 인자는 지원하지 않습니다")
        return func(*args)

    def _iterate(self, node: ast.GeneratorExp | ast.ListComp | ast.SetComp):
        if len(node.generators) != 1:
            raise ExprError("중첩 내포는 지원하지 않습니다")
        comp = node.generators[0]
        if comp.is_async or not isinstance(comp.target, ast.Name):
            raise ExprError("지원하지 않는 내포 표현입니다")
        source = self.visit(comp.iter)
        if source is MISSING or source is None:
            raise MissingValueError()
        name = comp.target.id
        saved = self.scope.get(name, MISSING)
        try:
            for item in source:
                self.scope[name] = item
                if all(self.visit(cond) for cond in comp.ifs):
                    yield self.visit(node.elt)
        finally:
            if saved is MISSING:
                self.scope.pop(name, None)
            else:
                self.scope[name] = saved

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> list:
        return list(self._iterate(node))

    def visit_ListComp(self, node: ast.ListComp) -> list:
        return list(self._iterate(node))

    def visit_SetComp(self, node: ast.SetComp) -> set:
        return set(self._iterate(node))


def parse(source: str) -> ast.Expression:
    try:
        return ast.parse(preprocess(source), mode="eval")
    except SyntaxError as exc:
        raise ExprError(f"표현식 문법 오류: {exc.msg}") from exc


def evaluate(source: str, scope: dict[str, Any]) -> Any:
    """표현식을 평가한다. 실패는 ExprError 계열로만 올라온다."""
    tree = parse(source)
    evaluator = _Evaluator(dict(scope))
    try:
        return evaluator.run(tree)
    except (ExprError, MissingValueError):
        raise
    except ZeroDivisionError as exc:
        raise ExprError("0 으로 나누었습니다") from exc
    except TypeError as exc:
        raise ExprError(f"값의 형식이 맞지 않습니다: {exc}") from exc
    except Exception as exc:  # 표현식 평가가 앱을 죽이지 않게 한다
        raise ExprError(f"평가 실패: {exc}") from exc


# ------------------------------------------------------- computed 자동 산출

def _is_derived(node: ast.AST) -> bool:
    """계산으로 만들어진 쪽인가 (함수 호출·사칙연산·내포)."""
    return isinstance(node, (ast.Call, ast.BinOp, ast.GeneratorExp, ast.ListComp, ast.SetComp))


def computed_source(source: str) -> str | None:
    """비교식에서 '정답' 에 해당하는 쪽을 골라 돌려준다.

    `fix` 문구가 "412km 를 기재하세요" 처럼 정답을 제시하려면 이 값이 필요하다.
    비교의 한쪽은 서류에 적힌 값, 다른 쪽은 계산으로 나온 값인 경우가 대부분이므로
    **계산된 쪽**을 고른다.

        dist_total == dist_out + dist_back      → 오른쪽 (412)
        sum(rows[].hours) == total_hours        → 왼쪽 (행별 합계)
    """
    try:
        tree = ast.parse(preprocess(source), mode="eval")
    except SyntaxError:
        return None
    node = tree.body
    if not isinstance(node, ast.Compare) or len(node.comparators) != 1:
        return None
    left, right = node.left, node.comparators[0]
    left_derived, right_derived = _is_derived(left), _is_derived(right)
    if left_derived == right_derived:
        # 양쪽 다 계산식이면 왼쪽, 양쪽 다 단순 참조면 제시할 정답이 없다.
        chosen = left if left_derived else None
    else:
        chosen = left if left_derived else right
    if chosen is None:
        return None
    return ast.unparse(chosen)


def compute(source: str, scope: dict[str, Any]) -> Any:
    """`{computed}` 에 넣을 값. 계산할 수 없으면 None."""
    chosen = computed_source(source)
    if chosen is None:
        return None
    try:
        value = evaluate(chosen, scope)
    except (ExprError, MissingValueError):
        return None
    return None if value is MISSING else value


def describe(value: Any) -> str:
    return format_value(value)
