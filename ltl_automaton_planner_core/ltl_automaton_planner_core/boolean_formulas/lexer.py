from functools import lru_cache

import ply.lex as lex

tokens = (
        "SYMBOL",
        "AND", "OR",
        "NOT",
        "TRUE",
        "LPAREN", "RPAREN")

t_SYMBOL = r"[a-z][a-zA-Z0-9_]*"
t_TRUE = r"1"
t_AND = r"&&"
t_OR = r"\|\|"
t_NOT = r"!"
t_LPAREN = r"\("
t_RPAREN = r"\)"

t_ignore = " \t\r\n"


def t_error(t):
    raise ValueError("Illegal guard character %r" % t.value[0])


@lru_cache(maxsize=1)
def _lexer_template():
    """Build the validated PLY lexer template lazily."""
    return lex.lex()


def get_lexer():
    """Return an independent lexer clone with an empty state stack."""
    lexer = _lexer_template().clone()
    lexer.lexstatestack = []
    return lexer
