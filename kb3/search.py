import re

class SearchStrParser:
    class ParsingError(RuntimeError):
        explanation = property(lambda self: self.args[0])

    class Sentinel:
        pass

    class Operator(Sentinel):
        pass

    class TopLevelOperator(Operator):
        precedence = 0

    class Not(Operator):
        valence = 1
        precedence = 3
        associativity = "right"
        op = staticmethod(lambda lhs: not lhs)

    class And(Operator):
        valence = 2
        precedence = 2
        associativity = "left"
        op = staticmethod(lambda lhs, rhs: lhs and rhs)

    class Or(Operator):
        valence = 2
        precedence = 1
        associativity = "left"
        op = staticmethod(lambda lhs, rhs: lhs or rhs)

    class POpen(Sentinel):
        pass

    class PClose(Sentinel):
        pass

    class ParserStr(str):
        valence = 0
        pass

    def __init__(self, query):
        self.full_query = query
        self.tokenize()
        self.tokens_to_rpn()
        self.validate_rpn()

    def add_token(self, token, consume=0):
        if not isinstance(token, SearchStrParser.Sentinel):
            # Convert str to ParserStr, so we can add arbitrary attributes.
            token = SearchStrParser.ParserStr(token)
        token.pos = len(self.full_query) - len(self.s)
        self.tokens.append(token)
        self.s = self.s[consume:]

    def error_on_token(self, message, token):
        raise SearchStrParser.ParsingError(
                "{}:\n{}\n{}\u2191".format(message, self.full_query,
                                           " " * token.pos))

    def tokenize(self):
        self.s = self.full_query
        self.tokens = []
        while True:
            self.s = self.s.lstrip()
            if not self.s:
                return

            if self.s[0] in "\"'":
                try:
                    end_quote = self.s[1:].index(self.s[0]) + 1
                except ValueError:
                    # Quoted string is not terminated in search string,
                    # so we simply ignore the quote.
                    self.s = self.s[1:]
                    continue
                self.add_token(self.s[1:end_quote], consume=end_quote + 1)

            elif self.s[0] == '!':
                self.add_token(SearchStrParser.Not(), consume=1)
            elif self.s[0] == '&':
                self.add_token(SearchStrParser.And(), consume=1)
            elif self.s[0] == '|':
                self.add_token(SearchStrParser.Or(), consume=1)
            elif self.s[0] == '(':
                self.add_token(SearchStrParser.POpen(), consume=1)
            elif self.s[0] == ')':
                self.add_token(SearchStrParser.PClose(), consume=1)
            else:
                m = re.search(r'\s|[!&|"\'()]', self.s)
                if not m:
                    # The current token stretches till the end of the input.
                    self.add_token(self.s, consume=len(self.s))
                else:
                    # A normal token.
                    self.add_token(self.s[:m.start()], consume=m.start())

    def tokens_to_rpn(self):
        # Create a new token list with "And" tokens inserted between all other
        # tokens except next to already present operators.
        tokens = []
        for i in range(len(self.tokens)):
            tokens.append(self.tokens[i])
            if i + 1 >= len(self.tokens):
                continue

            token_this = self.tokens[i]
            token_next = self.tokens[i + 1]
            if (    not isinstance(token_this, SearchStrParser.Operator) and
                    not isinstance(token_next, SearchStrParser.Operator) and
                    not isinstance(token_this, SearchStrParser.POpen) and
                    not isinstance(token_next, SearchStrParser.PClose)):
                and_op = SearchStrParser.And()
                and_op.pos = token_next.pos
                tokens.append(and_op)

        output = []
        op_stack = [SearchStrParser.TopLevelOperator]
        while tokens:
            token = tokens.pop(0)
            if isinstance(token, SearchStrParser.ParserStr):
                output.append(token)
            elif isinstance(token, SearchStrParser.Operator):
                while (isinstance(op_stack[-1], SearchStrParser.Operator) and
                       ((token.associativity == "left" and
                         token.precedence <= op_stack[-1].precedence)
                       or
                        token.precedence < op_stack[-1].precedence
                       )):
                    output.append(op_stack.pop())
                op_stack.append(token)
            elif isinstance(token, SearchStrParser.POpen):
                op_stack.append(token)
            elif isinstance(token, SearchStrParser.PClose):
                if not op_stack:
                    self.error_on_token("Unmatched close paren", token)
                while not isinstance(op_stack[-1], SearchStrParser.POpen):
                    output.append(op_stack.pop())
                    if not op_stack:
                        self.error_on_token("Unmatched close paren", token)
                op_stack.pop()
            else:
                raise NotImplementedError("Something gone wrong")

        while op_stack:
            token = op_stack.pop()
            if isinstance(token, SearchStrParser.POpen):
                self.error_on_token("Unmatched open paren", token)
            output.append(token)

        # Remove the trailing TopLevelOperator.
        output.pop()

        self.rpn = output
        return self.rpn

    def validate_rpn(self):
        stack_size = 0
        for token in self.rpn:
            stack_size += 1 - token.valence
            if stack_size <= 0:
                self.error_on_token("Syntax error around token", token)
        if stack_size != 1:
            raise SearchStrParser.ParsingError("Unknown syntax error")

    def evaluate(self, callback):
        stack = []
        for token in self.rpn:
            if isinstance(token, SearchStrParser.Operator):
                args = [stack.pop() for i in range(token.valence)]
                stack.append(token.op(*args))
            else:
                stack.append(callback(token))

        # Syntax errors should be cought in validate_rpn(), however, keep this
        # check here so we don't accidently hide a bug.
        if len(stack) != 1:
            raise RuntimeError("Stack gone wrong: " + repr(stack))
        return stack[0]
