import itertools
from collections import deque

from .lexer import get_lexer


class Expression(object):
    name = "Expression"

    def __iter__(self):
        raise NotImplementedError()

    def check(self, label):
        raise NotImplementedError()

    def distance(self, label):
        raise NotImplementedError()

    def nnf(self):
        return self


class SymbolExpression(Expression):
    def __init__(self, name):
        self.name = name
        self.symbol = name

    def __repr__(self):
        return "SymbolExpression(%s)" % str(self.symbol)

    def __iter__(self):
        for expr in [self]:
            yield expr

    def children(self):
        return []

    def check(self, label):
        return self.symbol in label

    def distance(self, label):
        if self.symbol in label:
            return 0
        else:
            return 1


class NotSymbolExpression(Expression):
    def __init__(self, name):
        self.name = "!%s" % name
        self.symbol = name

    def __repr__(self):
        return "NotSymbolExpression(%s)" % str(self.symbol)

    def __iter__(self):
        for expr in [self]:
            yield expr

    def children(self):
        return []

    def check(self, label):
        return self.symbol not in label

    def distance(self, label):
        if self.symbol not in label:
            return 0
        else:
            return 1


class TrueExpression(Expression):
    name = "TRUE"

    def __init__(self):
        pass

    def __repr__(self):
        return "TrueExpression()"

    def __iter__(self):
        for expr in [self]:
            yield expr

    def children(self):
        return []

    def check(self, label):
        return True

    def distance(self, label):
        return 0


class NotExpression(Expression):
    name = "NOT"

    def __init__(self, inner):
        self.inner = inner

    def __repr__(self):
        return "NotExpression(%s)" % str(self.inner)

    def __iter__(self):
        for expr in itertools.chain([self], self.inner):
            yield expr

    def children(self):
        return [self.inner]

    def check(self, label):
        return not self.inner.check(label)

    def nnf(self):
        if isinstance(self.inner, FalseExpression):
            return TrueExpression()
        elif isinstance(self.inner, TrueExpression):
            return FalseExpression()
        elif isinstance(self.inner, NotExpression):
            return self.inner.inner.nnf()
        elif isinstance(self.inner, NotSymbolExpression):
            return SymbolExpression(self.inner.symbol)
        elif isinstance(self.inner, SymbolExpression):
            s = NotSymbolExpression(self.inner.name)
            return s
        elif isinstance(self.inner, ORExpression):
            left = NotExpression(self.inner.left).nnf()
            right = NotExpression(self.inner.right).nnf()
            s = ANDExpression(left, right)
            return s
        elif isinstance(self.inner, ANDExpression):
            left = NotExpression(self.inner.left).nnf()
            right = NotExpression(self.inner.right).nnf()
            s = ORExpression(left, right)
            return s
        raise ValueError("Unexpected child of NotExpression")


class FalseExpression(TrueExpression):
    """Represent an unsatisfiable Boolean constant in negation normal form."""

    name = "FALSE"

    def __repr__(self):
        return "FalseExpression()"

    def check(self, label):
        return False

    def distance(self, label):
        return float("inf")


class BinExpression(Expression):
    def __init__(self, left, right):
        self.left = left
        self.right = right

    def __iter__(self):
        for expr in itertools.chain([self], self.left, self.right):
            yield expr

    def children(self):
        return [self.left, self.right]

    def nnf(self):
        self.left = self.left.nnf()
        self.right = self.right.nnf()
        return self


class ORExpression(BinExpression):
    name = "OR"

    def __repr__(self):
        return "ORExpression(%s, %s)" % (str(self.left), str(self.right))

    def check(self, label):
        return self.left.check(label) or self.right.check(label)

    def distance(self, label):
        ldist = self.left.distance(label)
        rdist = self.right.distance(label)
        return min([ldist, rdist])


class ANDExpression(BinExpression):
    name = "AND"

    def __repr__(self):
        return "ANDExpression(%s, %s)" % (str(self.left), str(self.right))

    def check(self, label):
        return self.left.check(label) and self.right.check(label)

    def distance(self, label):
        return self.left.distance(label) + self.right.distance(label)


class Parser(object):
    def __init__(self, formula):
        if not isinstance(formula, str) or not formula.strip():
            raise ValueError("A guard must be a non-empty string.")
        lexer = get_lexer()
        lexer.input(formula)
        self.formula = formula
        self.tokens = deque(lexer)

    def symbols(self):
        syms = list()
        for token in self.tokens:
            if token.type == "SYMBOL":
                syms += [token.value]
        return list(set(syms))

    def parse(self):
        expr = self.orx()
        if self.tokens:
            raise ValueError("Unexpected trailing guard token: %s" % self.tokens[0])
        expr = expr.nnf()
        expr.formula = self.formula
        return expr

    def orx(self):
        lhs = self.andx()
        if len(self.tokens) == 0 or self.tokens[0].type == "RPAREN":
            return lhs
        elif self.tokens[0].type == "OR":
            self.tokens.popleft()
            rhs = self.andx()
            lhs = ORExpression(lhs, rhs)
            while len(self.tokens) > 0 and self.tokens[0].type == "OR":
                self.tokens.popleft()
                rhs = self.andx()
                lhs = ORExpression(lhs, rhs)
            return lhs
        else:
            raise ValueError("Expected OR, RPAREN or nothing but got %s" % self.tokens[0])

    def andx(self):
        lhs = self.notx()
        if len(self.tokens) == 0 or self.tokens[0].type in ["OR", "RPAREN"]:
            return lhs
        elif self.tokens[0].type == "AND":
            self.tokens.popleft()
            rhs = self.notx()
            lhs = ANDExpression(lhs, rhs)
            while len(self.tokens) > 0 and self.tokens[0].type == "AND":
                self.tokens.popleft()
                rhs = self.notx()
                lhs = ANDExpression(lhs, rhs)
            return lhs
        else:
            raise ValueError("Expected OR, AND or nothing but got %s" % self.tokens[0])

    def notx(self):
        if not self.tokens:
            raise ValueError("Expected a guard operand.")
        if self.tokens[0].type == "NOT":
            self.tokens.popleft()
            return NotExpression(self.notx())
        else:
            return self.parx()

    def parx(self):
        if not self.tokens:
            raise ValueError("Expected a guard operand.")
        if self.tokens[0].type == "LPAREN":
            self.tokens.popleft()
            expr = self.orx()
            if not self.tokens or self.tokens[0].type != "RPAREN":
                raise ValueError("Expected a closing guard parenthesis.")
            self.tokens.popleft()
        elif self.tokens[0].type == "SYMBOL":
            expr = SymbolExpression(self.tokens[0].value)
            self.tokens.popleft()
        elif self.tokens[0].type == "TRUE":
            expr = TrueExpression()
            self.tokens.popleft()
        else:
            raise ValueError("Expected LPAREN or SYMBOL but got %s" % self.tokens[0])
        return expr


def parse(formula):
    parser = Parser(formula)
    return parser.parse()
