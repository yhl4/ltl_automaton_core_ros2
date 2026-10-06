import ply.lex as lex

tokens = (
        "SYMBOL",
        "AND", "OR",
        "NOT",
        "TRUE",
        "LPAREN", "RPAREN")

t_SYMBOL = r"[a-z]+[a-z0-9_]*"
t_TRUE = r"1"
t_AND = r"&&"
t_OR = r"\|\|"
t_NOT = r"!"
t_LPAREN = r"\("
t_RPAREN = r"\)"

t_ignore = " \t\r\n"


def t_error(t):
    raise ValueError("Illegal guard character %r" % t.value[0])


def get_lexer():
    return lex.lex()
